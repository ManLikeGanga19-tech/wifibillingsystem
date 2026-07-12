"""Transactional SMS: the receipt and the renewal nudge.

A hotspot that silently drops people offline gets re-bought by whoever remembers to.
One that texts "you're online until 4pm" and then "your time's almost up — renew" gets
re-bought on purpose. These are the two messages that turn a session into a habit.

The provider itself (Africa's Talking) is exercised elsewhere; here we prove the
TRIGGERS fire, exactly once, to the right number, and never when the ISP opted out.
"""

import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Message
from apps.notifications.providers.dummy import DummyProvider
from apps.provisioning.models import Session
from apps.provisioning.tasks import warn_expiring_sessions

from .factories import OperatorFactory, PlanFactory, RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db


def _pay_callback(client, checkout_id):
    stk = {
        "CheckoutRequestID": checkout_id,
        "ResultCode": 0,
        "ResultDesc": "ok",
        "CallbackMetadata": {"Item": [{"Name": "MpesaReceiptNumber", "Value": "R1"}]},
    }
    url = reverse("daraja-callback", args=[settings.DARAJA_CALLBACK_TOKEN])
    return client.post(
        url, data=json.dumps({"Body": {"stkCallback": stk}}), content_type="application/json"
    )


def _sms_to(phone):
    return [body for to, body in DummyProvider.sent if to == phone]


class TestPaymentConfirmation:
    def test_a_paid_customer_gets_an_online_receipt(
        self, api_client, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, phone="254712345678")

        with django_capture_on_commit_callbacks(execute=True):
            _pay_callback(api_client, tx.checkout_request_id)

        texts = _sms_to("254712345678")
        assert len(texts) == 1
        assert "online" in texts[0].lower()
        assert Message.objects.filter(
            to_phone="254712345678", category=Message.Category.PAYMENT
        ).exists()

    def test_no_sms_when_the_isp_switched_it_off(
        self, api_client, django_capture_on_commit_callbacks
    ):
        op = OperatorFactory(notify_customers_sms=False)
        RouterFactory(operator=op)
        tx = TransactionFactory(operator=op, phone="254712345678")

        with django_capture_on_commit_callbacks(execute=True):
            _pay_callback(api_client, tx.checkout_request_id)

        assert _sms_to("254712345678") == []

    def test_a_retried_provision_does_not_double_text(
        self, api_client, django_capture_on_commit_callbacks
    ):
        """activate() returns early if already active, so a duplicate callback (or a
        retry) must not send a second receipt."""
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, phone="254712345678")

        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                _pay_callback(api_client, tx.checkout_request_id)

        assert len(_sms_to("254712345678")) == 1


class TestExpiryWarning:
    def _active_session(self, *, mins_left, warned=False, phone="254700111222"):
        router = RouterFactory()
        plan = PlanFactory(operator=router.operator, name="1 Hour Express")
        tx = TransactionFactory(operator=router.operator, plan=plan, phone=phone)
        now = timezone.now()
        return Session.objects.create(
            operator=router.operator, plan=plan, router=router, transaction=tx,
            hotspot_username=phone, starts_at=now - timedelta(minutes=50),
            expires_at=now + timedelta(minutes=mins_left),
            status=Session.Status.ACTIVE,
            expiry_warned_at=now if warned else None,
        )

    def test_a_session_expiring_soon_is_warned_once(
        self, django_capture_on_commit_callbacks
    ):
        s = self._active_session(mins_left=8)

        with django_capture_on_commit_callbacks(execute=True):
            warn_expiring_sessions()
            warn_expiring_sessions()  # second run must not re-text

        assert len(_sms_to("254700111222")) == 1
        assert "runs out" in _sms_to("254700111222")[0].lower()
        s.refresh_from_db()
        assert s.expiry_warned_at is not None

    def test_a_session_with_plenty_of_time_is_not_warned(
        self, django_capture_on_commit_callbacks
    ):
        self._active_session(mins_left=45)
        with django_capture_on_commit_callbacks(execute=True):
            warn_expiring_sessions()
        assert _sms_to("254700111222") == []

    def test_an_already_expired_session_is_not_warned(
        self, django_capture_on_commit_callbacks
    ):
        """Warning someone whose time is already gone is just noise."""
        s = self._active_session(mins_left=8)
        Session.objects.filter(pk=s.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        with django_capture_on_commit_callbacks(execute=True):
            warn_expiring_sessions()
        assert _sms_to("254700111222") == []

    def test_renewing_resets_the_warning_so_the_next_window_warns_again(self):
        """A fresh window is a fresh chance to warn — expiry_warned_at clears on
        activation."""
        from apps.provisioning.services import activate

        s = self._active_session(mins_left=8, warned=True)
        s.status = Session.Status.PENDING  # simulate a renew re-provisioning it
        s.save()
        activate(s)
        s.refresh_from_db()
        assert s.expiry_warned_at is None
