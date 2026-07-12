"""The paid-but-never-connected bug — and the guarantee that it can't happen again.

A customer sends the STK push, pays, and then... the portal spins forever. That is the
single most expensive failure this system can have: we took the money and delivered
nothing, with no error the customer could act on. It happened because the portal could
only recognise a session going ACTIVE — it had no way to see a provisioning FAILURE, so
a failure was indistinguishable from "still working".

The fix has two halves, both tested here:

  PREVENTIVE — if we already know we cannot connect them (the ISP has no router), we
  refuse BEFORE the push. No money changes hands for a service we cannot deliver.

  RESILIENT — if provisioning fails AFTER payment (a router blinked), the transaction
  always ends in a state the portal can read: `provisioning: failed`, with the money
  safe, a retry, and an automatic re-attempt when the router returns.
"""

import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.urls import reverse

from apps.payments.models import Transaction
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session

from .factories import PlanFactory, RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db

STK = "/api/v1/payments/stk-push/"


def _stk_ok(mocker):
    mocker.patch(
        "apps.payments.services.DarajaClient.stk_push",
        return_value={"CheckoutRequestID": "ws_CO_test", "MerchantRequestID": "m-1"},
    )
    mocker.patch("apps.payments.services.DarajaClient.__init__", return_value=None)


def _callback(checkout_id, result_code=0):
    stk = {
        "CheckoutRequestID": checkout_id,
        "ResultCode": result_code,
        "ResultDesc": "ok" if result_code == 0 else "cancelled",
    }
    if result_code == 0:
        stk["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": 30},
                {"Name": "MpesaReceiptNumber", "Value": "NLJ7RT61SV"},
            ]
        }
    return {"Body": {"stkCallback": stk}}


def _post_callback(client, checkout_id, result_code=0):
    url = reverse("daraja-callback", args=[settings.DARAJA_CALLBACK_TOKEN])
    return client.post(
        url, data=json.dumps(_callback(checkout_id, result_code)), content_type="application/json"
    )


def _status(client, tx):
    return client.get(f"/api/v1/payments/status/{tx.public_id}/").json()


# ---- PREVENTIVE: don't charge for what we can't deliver ----------------------------


class TestRefuseWhenWeCannotConnect:
    def test_initiate_refuses_when_the_operator_has_no_router(self, mocker):
        """The most common cause of the spinner: an ISP is set up for billing but has
        not enrolled a router. Charging them would be taking money for a service we
        cannot deliver — so we refuse at the door, before the push, and take nothing."""
        from apps.payments.services import ProvisioningUnavailable, initiate_stk_push

        _stk_ok(mocker)
        plan = PlanFactory()  # its operator has no router
        assert not plan.operator.routers.exists()

        with pytest.raises(ProvisioningUnavailable):
            initiate_stk_push(phone="0712345678", plan=plan)

        # Nothing was charged: no transaction, and the push was never sent.
        assert Transaction.objects.filter(plan=plan).count() == 0

    def test_the_view_maps_the_refusal_to_a_clean_409(self, api_client, mocker):
        """And the customer sees a clear "not ready", not a generic error or — worse —
        a spinner."""
        from apps.payments import views

        _stk_ok(mocker)
        router = RouterFactory()
        plan = PlanFactory(operator=router.operator)
        mocker.patch.object(
            views,
            "initiate_stk_push",
            side_effect=views.ProvisioningUnavailable("This hotspot is not ready yet."),
        )
        resp = api_client.post(
            STK, {"phone": "0712345678", "plan_id": plan.id, "router_id": router.id}, format="json"
        )
        assert resp.status_code == 409
        assert resp.json()["reason"] == "no_router"

    def test_initiate_proceeds_when_a_router_exists(self, mocker):
        from apps.payments.services import initiate_stk_push

        _stk_ok(mocker)
        router = RouterFactory()
        plan = PlanFactory(operator=router.operator)

        tx = initiate_stk_push(phone="0712345678", plan=plan)
        assert tx.checkout_request_id == "ws_CO_test"


# ---- RESILIENT: a paid customer always reaches a readable state --------------------


class TestPaidButProvisioningFails:
    def test_router_deleted_between_push_and_payment_is_visible_not_a_void(
        self, api_client, django_capture_on_commit_callbacks
    ):
        """The race: they pay, and the ISP's last router is gone by the time the
        callback lands. No session can be created (router is required) — so the failure
        is recorded on the TRANSACTION, and the portal sees `failed`, not a null session
        it would poll forever."""
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        router.delete()  # the void that used to strand the customer

        with django_capture_on_commit_callbacks(execute=True):
            _post_callback(api_client, tx.checkout_request_id)

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.SUCCESS  # they DID pay
        assert tx.provision_error  # ...and we recorded that we couldn't connect them

        body = _status(api_client, tx)
        assert body["provisioning"] == "failed"
        assert "payment is safe" in body["provision_message"].lower()

    def test_router_unreachable_marks_the_session_failed_and_portal_sees_it(
        self, api_client, mocker, django_capture_on_commit_callbacks
    ):
        """The router exists but won't accept the user (tunnel down). The session is
        created and marked FAILED — and the portal must see `failed`, where before it
        only ever saw a non-active session as 'still connecting'.

        max_retries=0 makes the first failure the terminal one, so this exercises the
        'retries exhausted -> mark FAILED' path deterministically (eager Celery does
        not accumulate real retries)."""
        from apps.provisioning.tasks import provision_transaction

        mocker.patch.object(provision_transaction, "max_retries", 0)
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)

        with patch.object(DummyAdapter, "activate_user", side_effect=RuntimeError("router down")):
            with django_capture_on_commit_callbacks(execute=True):
                _post_callback(api_client, tx.checkout_request_id)

        session = Session.objects.get(transaction=tx)
        assert session.status == Session.Status.FAILED
        assert "router down" in session.provision_error

        body = _status(api_client, tx)
        assert body["provisioning"] == "failed"
        assert body["session_active"] is False

    def test_the_happy_path_still_reports_active(
        self, api_client, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        with django_capture_on_commit_callbacks(execute=True):
            _post_callback(api_client, tx.checkout_request_id)

        body = _status(api_client, tx)
        assert body["provisioning"] == "active"
        assert body["session_active"] is True
        assert body["session"]["hotspot_username"] == tx.phone

    def test_a_pending_payment_reports_pending_not_connecting(self, api_client):
        tx = TransactionFactory()  # never paid
        body = _status(api_client, tx)
        assert body["provisioning"] == "pending"


# ---- RECOVERY: retry, and automatic reconnection -----------------------------------


class TestRecovery:
    def test_customer_retry_re_attempts_and_connects(
        self, api_client, mocker, django_capture_on_commit_callbacks
    ):
        from apps.provisioning.tasks import provision_transaction

        mocker.patch.object(provision_transaction, "max_retries", 0)
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)

        # First attempt fails (router down)...
        with patch.object(DummyAdapter, "activate_user", side_effect=RuntimeError("down")):
            with django_capture_on_commit_callbacks(execute=True):
                _post_callback(api_client, tx.checkout_request_id)
        assert _status(api_client, tx)["provisioning"] == "failed"

        # ...the router comes back, the customer taps retry, and they connect.
        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(f"/api/v1/payments/status/{tx.public_id}/retry/")
        assert resp.status_code == 200

        body = _status(api_client, tx)
        assert body["provisioning"] == "active"
        assert ("activate", tx.phone) in DummyAdapter.calls

    def test_retry_before_payment_is_refused(self, api_client):
        tx = TransactionFactory()  # not paid
        resp = api_client.post(f"/api/v1/payments/status/{tx.public_id}/retry/")
        assert resp.status_code == 409

    def test_retry_on_unknown_payment_404s(self, api_client):
        import uuid

        resp = api_client.post(f"/api/v1/payments/status/{uuid.uuid4()}/retry/")
        assert resp.status_code == 404

    def test_beat_auto_reconnects_recently_failed_sessions(self):
        """The router blinked for thirty seconds; five people paid during the outage.
        They must all reconnect on their own, without a support call."""
        from apps.provisioning.tasks import retry_failed_provisions

        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        # A failed session whose window is still open.
        from datetime import timedelta

        from django.utils import timezone

        session = Session.objects.create(
            operator=router.operator,
            plan=tx.plan,
            router=router,
            transaction=tx,
            hotspot_username=tx.phone,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1),
            status=Session.Status.FAILED,
            provision_error="router down",
        )

        retry_failed_provisions()  # eager: re-attempts inline

        session.refresh_from_db()
        assert session.status == Session.Status.ACTIVE
        assert ("activate", tx.phone) in DummyAdapter.calls

    def test_beat_leaves_expired_windows_alone(self):
        """Don't silently connect someone whose paid time already elapsed while they
        walked away — re-paying is cleaner than a surprise connection."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.provisioning.tasks import retry_failed_provisions

        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator)
        session = Session.objects.create(
            operator=router.operator,
            plan=tx.plan,
            router=router,
            transaction=tx,
            hotspot_username=tx.phone,
            starts_at=timezone.now() - timedelta(hours=2),
            expires_at=timezone.now() - timedelta(minutes=1),  # already over
            status=Session.Status.FAILED,
        )

        retry_failed_provisions()

        session.refresh_from_db()
        assert session.status == Session.Status.FAILED  # untouched
