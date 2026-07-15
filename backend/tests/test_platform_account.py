"""The ISP's account WITH WIFI.OS: what they owe us, and topping it up by M-Pesa.

Distinct from the wallet (money we hold FOR them). An ISP selling through their own
gateway has no wallet balance at all, yet still owes us for every SMS we send on their
behalf — which is exactly why SMS could no longer be bought out of the wallet.

The things worth breaking a build over:
  * an ISP is never billed twice for one message, however many times the task retries;
  * an ISP is never credited twice for one top-up, however many times Safaricom replays
    the callback (they do);
  * a top-up whose callback is LOST still lands — otherwise we hold their money AND
    withhold the service;
  * the "you are out of balance" warning is never itself billed to the empty balance.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing import platform_account as pa
from apps.billing.models import PlatformLedgerEntry, TopUp
from apps.notifications.models import Message, MessagingSettings
from apps.notifications.providers.dummy import DummyProvider
from apps.notifications.tasks import send_message, warn_low_platform_balance

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

ACCOUNT_URL = "/api/v1/billing/account/"
ALERTS_URL = "/api/v1/billing/account/alerts/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def drain(operator):
    """Every operator is born with a welcome credit. Tests about an EMPTY account have to
    actually empty it."""
    PlatformLedgerEntry.objects.filter(operator=operator).delete()


def a_message(operator, body="hi"):
    return Message.objects.create(operator=operator, to_phone="254700000001", body=body)


# --- the balance --------------------------------------------------------------------------


def test_a_new_isp_starts_with_a_balance_so_their_first_receipt_sends():
    """The managed gateway promises it works on day one. A zero balance would make that a
    lie — the first customer would pay and hear nothing back."""
    operator = OperatorFactory(slug="newborn")

    assert pa.balance(operator) == pa.WELCOME_CREDIT
    assert pa.can_send_sms(operator) is True


def test_the_balance_may_go_negative_because_this_is_postpaid():
    """Fees accrue whether or not they have prepaid. A negative balance is what they OWE —
    it is not an error state, it is the invoice."""
    operator = OperatorFactory(slug="owing")
    drain(operator)
    PlatformLedgerEntry.objects.create(
        operator=operator, amount=Decimal("-500.00"),
        reason=PlatformLedgerEntry.Reason.COMMISSION, memo="fee",
    )

    assert pa.balance(operator) == Decimal("-500.00")
    # ...but they cannot spend more of OUR money on SMS while they are in the red.
    assert pa.can_send_sms(operator) is False


# --- billing an SMS -------------------------------------------------------------------------


def test_a_sent_sms_is_charged_at_the_published_price():
    operator = OperatorFactory(slug="charged")
    before = pa.balance(operator)
    msg = a_message(operator)

    pa.charge_sms(operator, msg, segments=1)

    assert pa.balance(operator) == before - pa.SMS_PRICE


def test_a_long_message_costs_more_because_the_gateway_charges_us_more():
    """SMS is billed per 160-character segment. Charging one credit for a 400-character
    message would mean we pay for three and bill for one."""
    from apps.notifications.tasks import _segments

    assert _segments("x" * 160) == 1
    assert _segments("x" * 161) == 2
    assert _segments("x" * 307) == 3
    assert pa.sms_cost(3) == pa.SMS_PRICE * 3


def test_an_isp_is_never_billed_twice_for_one_message():
    """The retry guard. A Celery task that runs three times must not bill three times."""
    operator = OperatorFactory(slug="retry")
    before = pa.balance(operator)
    msg = a_message(operator)

    pa.charge_sms(operator, msg)
    pa.charge_sms(operator, msg)  # the retry
    pa.charge_sms(operator, msg)

    assert PlatformLedgerEntry.objects.filter(message=msg).count() == 1
    assert pa.balance(operator) == before - pa.SMS_PRICE


def test_an_isp_with_no_balance_does_not_send_on_the_managed_gateway():
    """We would be handing the gateway money the ISP never gave us."""
    operator = OperatorFactory(slug="empty")
    MessagingSettings.objects.create(operator=operator)  # managed
    drain(operator)
    msg = a_message(operator)

    send_message(msg.pk)

    msg.refresh_from_db()
    assert msg.status == Message.Status.FAILED
    assert "balance" in msg.error.lower()


def test_an_isp_on_their_own_gateway_is_not_billed_by_us():
    """Their provider bills them directly. Metering them too would charge twice."""
    operator = OperatorFactory(slug="byo")
    MessagingSettings.objects.create(operator=operator, sms_provider="mobilesasa")
    drain(operator)
    msg = a_message(operator)

    send_message(msg.pk)

    msg.refresh_from_db()
    assert msg.status == Message.Status.SENT  # sent despite a zero balance with US
    assert not PlatformLedgerEntry.objects.filter(message=msg).exists()


# --- the warning that must always get through -------------------------------------------------


def test_the_low_balance_warning_is_not_billed_to_the_balance_it_is_warning_about():
    """The trap. If the "you are out of balance" SMS were billed like any other, it could
    not be sent at exactly the moment it matters — and we would be charging an ISP for the
    privilege of being told they are broke."""
    operator = OperatorFactory(slug="broke")
    MessagingSettings.objects.create(operator=operator)
    drain(operator)  # nothing left at all
    msg = Message.objects.create(
        operator=operator,
        to_phone="254700000001",
        body="You are out of balance",
        category=Message.Category.ALERT,
    )

    send_message(msg.pk)

    msg.refresh_from_db()
    assert msg.status == Message.Status.SENT  # it got through
    assert not PlatformLedgerEntry.objects.filter(message=msg).exists()  # and was free
    assert pa.balance(operator) == Decimal("0.00")


def test_a_low_balance_isp_is_warned_once_per_fall_not_every_hour():
    operator = OperatorFactory(slug="nag", contact_phone="254700000009")
    config = MessagingSettings.objects.create(
        operator=operator, low_balance_threshold=Decimal("200.00")
    )
    drain(operator)
    DummyProvider.sent = []

    assert warn_low_platform_balance() == 1
    assert warn_low_platform_balance() == 0  # already told them
    config.refresh_from_db()
    assert config.low_balance_alerted_at is not None


def test_the_alarm_is_rearmed_once_they_top_back_up():
    operator = OperatorFactory(slug="rearm", contact_phone="254700000009")
    config = MessagingSettings.objects.create(
        operator=operator, low_balance_threshold=Decimal("200.00")
    )
    drain(operator)
    warn_low_platform_balance()

    pa.grant(operator, Decimal("5000.00"), memo="topped up")
    warn_low_platform_balance()  # recovery pass clears the flag

    config.refresh_from_db()
    assert config.low_balance_alerted_at is None

    # And a SECOND fall warns again, rather than staying silent forever.
    drain(operator)
    assert warn_low_platform_balance() == 1


# --- topping up ---------------------------------------------------------------------------------


def a_topup(operator, bundle_id="growth", checkout="ws_CO_1"):
    b = pa.bundle(bundle_id)
    return TopUp.objects.create(
        operator=operator,
        amount=b.price,
        credit=b.credit,
        bundle=bundle_id,
        phone="254700000001",
        checkout_request_id=checkout,
    )


def test_a_paid_topup_credits_the_account_including_its_bonus():
    """The volume discount is expressed as bonus CREDIT, because the balance is in
    shillings and an SMS has one price."""
    from apps.billing.topup import _finish

    operator = OperatorFactory(slug="topper")
    drain(operator)
    row = a_topup(operator, "growth")  # pay 3,750 -> credit 4,000

    _finish(row, ok=True, receipt="QWE123")

    assert pa.balance(operator) == Decimal("4000.00")
    assert pa.bundle("growth").sms == 5000


def test_a_replayed_callback_does_not_credit_twice():
    """Safaricom replays callbacks. Crediting an ISP twice for one payment is us giving
    away money."""
    from apps.billing.topup import _finish

    operator = OperatorFactory(slug="replay")
    drain(operator)
    row = a_topup(operator, "starter")

    _finish(row, ok=True, receipt="QWE123")
    _finish(row, ok=True, receipt="QWE123")
    _finish(row, ok=True, receipt="QWE123")

    assert PlatformLedgerEntry.objects.filter(topup=row).count() == 1
    assert pa.balance(operator) == Decimal("800.00")


def test_a_failed_topup_credits_nothing():
    from apps.billing.topup import _finish

    operator = OperatorFactory(slug="failed")
    drain(operator)
    row = a_topup(operator, "starter")

    _finish(row, ok=False, desc="Request cancelled by user")

    row.refresh_from_db()
    assert row.status == TopUp.Status.FAILED
    assert pa.balance(operator) == Decimal("0.00")


def test_a_lost_callback_is_settled_by_reconciliation(monkeypatch):
    """THE lesson from the hotspot bug. If a callback never arrives and nothing chases it,
    the ISP has paid us and their SMS stays off — we hold their money AND withhold the
    service."""
    from apps.billing import topup as topup_mod

    operator = OperatorFactory(slug="lost")
    drain(operator)
    row = a_topup(operator, "starter")

    class FakeDaraja:
        def stk_query(self, checkout_request_id):
            return {"ResultCode": "0", "ResultDesc": "Success"}

    monkeypatch.setattr(
        topup_mod.DarajaClient, "for_platform", classmethod(lambda cls: FakeDaraja())
    )

    topup_mod.reconcile(row)  # no callback ever came

    row.refresh_from_db()
    assert row.status == TopUp.Status.SUCCESS
    assert pa.balance(operator) == Decimal("800.00")


def test_the_callback_and_the_reconciler_racing_each_other_credit_once(monkeypatch):
    """Both paths can fire for the same top-up. Idempotency is what makes that safe."""
    from apps.billing import topup as topup_mod

    operator = OperatorFactory(slug="race")
    drain(operator)
    row = a_topup(operator, "starter", checkout="ws_CO_race")

    class FakeDaraja:
        def stk_query(self, checkout_request_id):
            return {"ResultCode": "0", "ResultDesc": "Success"}

    monkeypatch.setattr(
        topup_mod.DarajaClient, "for_platform", classmethod(lambda cls: FakeDaraja())
    )

    topup_mod.handle_callback(
        {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": "ws_CO_race",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [{"Name": "MpesaReceiptNumber", "Value": "QWE999"}]
                    },
                }
            }
        }
    )
    topup_mod.reconcile(row)

    assert PlatformLedgerEntry.objects.filter(topup=row).count() == 1
    assert pa.balance(operator) == Decimal("800.00")


# --- the API ---------------------------------------------------------------------------


def test_the_account_endpoint_reports_the_balance_in_shillings_AND_messages():
    """"KSh 640" tells an ISP nothing about whether tonight's reminders will go out."""
    operator = OperatorFactory(slug="api")

    body = owner(operator).get(ACCOUNT_URL).json()

    assert Decimal(body["balance"]) == pa.WELCOME_CREDIT
    assert body["sms_remaining"] == int(pa.WELCOME_CREDIT / pa.SMS_PRICE)
    assert body["can_send_sms"] is True
    assert len(body["bundles"]) == len(pa.BUNDLES)


def test_alert_numbers_are_normalised_and_junk_is_refused():
    operator = OperatorFactory(slug="alerts")

    ok = owner(operator).patch(
        ALERTS_URL, {"alert_phones": ["0716170397"], "low_balance_threshold": "500"},
        format="json",
    )
    assert ok.status_code == 200
    assert ok.json()["alert_phones"] == ["254716170397"]  # normalised
    assert Decimal(ok.json()["low_balance_threshold"]) == Decimal("500.00")

    bad = owner(operator).patch(ALERTS_URL, {"alert_phones": ["not-a-phone"]}, format="json")
    assert bad.status_code == 400


def test_one_isp_cannot_see_anothers_balance():
    other = OperatorFactory(slug="other")
    pa.grant(other, Decimal("50000.00"), memo="theirs")
    operator = OperatorFactory(slug="mine")

    body = owner(operator).get(ACCOUNT_URL).json()

    assert Decimal(body["balance"]) == pa.WELCOME_CREDIT  # ours, not theirs


def test_topup_uses_the_PLATFORM_daraja_not_a_bare_client(monkeypatch):
    """SECURITY/CORRECTNESS: a top-up is the ISP paying US, so it must go on Danamo's
    paybill (DarajaClient.for_platform), not a bare DarajaClient() — which, post-refactor,
    raises 'credentials not configured' and would break every top-up in production. The
    mocked tests hid this; this one pins the construction path."""
    from apps.billing import topup as topup_mod

    operator = OperatorFactory(slug="platclient")
    calls = {"for_platform": 0}

    class FakePlatform:
        def stk_push(self, **kwargs):
            calls["for_platform"] += 1
            return {"CheckoutRequestID": "ws_CO_x", "MerchantRequestID": "m"}

    monkeypatch.setattr(
        topup_mod.DarajaClient, "for_platform", classmethod(lambda cls: FakePlatform())
    )
    # A bare DarajaClient() must NOT be relied on — make it explode if used.
    monkeypatch.setattr(
        topup_mod.DarajaClient, "__init__",
        lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("bare client used")),
    )

    topup_mod.initiate(operator=operator, phone="254700000001", amount=100)

    assert calls["for_platform"] == 1
