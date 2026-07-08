"""The money tests: callback idempotency and the payment -> provisioning flow."""

import json

import pytest
from django.conf import settings
from django.urls import reverse

from apps.payments.models import Transaction
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session

from .factories import RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db


def callback_payload(checkout_id, result_code=0, receipt="NLJ7RT61SV", amount=30):
    stk = {
        "MerchantRequestID": "29115-34620561-1",
        "CheckoutRequestID": checkout_id,
        "ResultCode": result_code,
        "ResultDesc": "The service request is processed successfully."
        if result_code == 0
        else "Request cancelled by user",
    }
    if result_code == 0:
        stk["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "TransactionDate", "Value": 20260708123456},
                {"Name": "PhoneNumber", "Value": 254712345678},
            ]
        }
    return {"Body": {"stkCallback": stk}}


def post_callback(client, payload):
    url = reverse("daraja-callback", args=[settings.DARAJA_CALLBACK_TOKEN])
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class TestCallbackIdempotency:
    def test_success_callback_marks_paid_and_provisions(
        self, api_client, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        with django_capture_on_commit_callbacks(execute=True):
            resp = post_callback(api_client, callback_payload(tx.checkout_request_id))

        assert resp.status_code == 200
        assert resp.json()["ResultCode"] == 0
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.SUCCESS
        assert tx.mpesa_receipt == "NLJ7RT61SV"
        assert tx.raw_callback is not None  # raw JSON stored verbatim
        # Celery eager mode: session was created and activated on the dummy router
        session = Session.objects.get(transaction=tx)
        assert session.status == Session.Status.ACTIVE
        assert ("activate", tx.phone) in DummyAdapter.calls

    def test_duplicate_callback_is_noop(
        self, api_client, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        payload = callback_payload(tx.checkout_request_id)

        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                assert post_callback(api_client, payload).status_code == 200

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.SUCCESS
        assert Session.objects.filter(transaction=tx).count() == 1
        # activate called exactly once despite three callbacks
        assert DummyAdapter.calls.count(("activate", tx.phone)) == 1

    def test_failure_after_success_does_not_downgrade(self, api_client):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        post_callback(api_client, callback_payload(tx.checkout_request_id, result_code=0))
        # A late/contradictory failure callback must not overwrite success
        post_callback(api_client, callback_payload(tx.checkout_request_id, result_code=1032))
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.SUCCESS

    def test_cancelled_by_user(self, api_client):
        tx = TransactionFactory()
        post_callback(api_client, callback_payload(tx.checkout_request_id, result_code=1032))
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.FAILED
        assert not Session.objects.filter(transaction=tx).exists()

    def test_unknown_checkout_id_returns_200(self, api_client):
        resp = post_callback(api_client, callback_payload("ws_CO_does_not_exist"))
        assert resp.status_code == 200  # never give Safaricom an error

    def test_wrong_token_404s(self, api_client):
        resp = api_client.post(
            "/api/v1/payments/callback/wrong-token/",
            data=json.dumps(callback_payload("x")),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_malformed_body_returns_200(self, api_client):
        url = reverse("daraja-callback", args=[settings.DARAJA_CALLBACK_TOKEN])
        resp = api_client.post(url, data="not-json{", content_type="application/json")
        assert resp.status_code == 200


class TestSTKInitiation:
    def test_initiate_creates_pending_tx(self, api_client, mocker, router):
        from tests.factories import PlanFactory

        plan = PlanFactory(operator=router.operator)
        mocker.patch(
            "apps.payments.services.DarajaClient.stk_push",
            return_value={"CheckoutRequestID": "ws_CO_abc123", "MerchantRequestID": "m-1"},
        )
        mocker.patch("apps.payments.services.DarajaClient.__init__", return_value=None)
        resp = api_client.post(
            "/api/v1/payments/stk-push/",
            {"phone": "0712 345 678", "plan_id": plan.id},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        tx = Transaction.objects.get(checkout_request_id="ws_CO_abc123")
        assert tx.status == Transaction.Status.PENDING
        assert tx.phone == "254712345678"  # normalized
        assert str(tx.public_id) == resp.json()["transaction_id"]

    def test_status_polling(self, api_client):
        tx = TransactionFactory()
        resp = api_client.get(f"/api/v1/payments/status/{tx.public_id}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
