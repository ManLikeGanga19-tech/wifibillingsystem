"""Payment gateways: whose account the money lands in, and what that means for the wallet.

This is where Phase 1's invariant meets the real payment path. An ISP on their OWN M-Pesa
shortcode is paid instantly and directly; we never touch that money. So:

  * the sale is recorded (it is revenue, and the basis of the fee we invoice),
  * and it must NEVER become withdrawable from us.

Plus the things that make a webhook safe: a guessed URL must not forge a paid session, and
one ISP must not be able to settle another's payment through their own hook.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry, Settlement
from apps.billing.services import recorded_revenue, withdrawable_balance
from apps.payments.gateways import get_gateway
from apps.payments.gateways.base import GatewayError
from apps.payments.models import GatewayCredential, Transaction
from apps.payments.services import process_stk_callback

from .factories import OperatorFactory, PlanFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db

GATEWAYS_URL = "/api/v1/payments/gateways/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def give_mpesa_keys(operator, **overrides):
    row = GatewayCredential(operator=operator, gateway="mpesa")
    row.values = {
        "collection_method": "paybill",
        "shortcode": "545500",
        "consumer_key": "ck-live",
        "consumer_secret": "cs-live",
        "passkey": "pk-live",
        **overrides,
    }
    row.save()
    return row


def paid_callback(checkout_id, receipt="QWE123"):
    return {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": checkout_id,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 100},
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                    ]
                },
            }
        }
    }


# --- which gateway, and therefore whose money -------------------------------------------


def test_a_new_isp_collects_on_our_paybill_so_they_can_sell_today():
    """Safaricom takes weeks to approve a shortcode. An ISP who cannot take money while
    they wait is an ISP who signs up with somebody else."""
    operator = OperatorFactory(slug="newborn")

    gateway = get_gateway(operator)

    assert gateway.id == "wifios"
    assert gateway.settlement == Settlement.PLATFORM


def test_an_isp_on_their_own_shortcode_settles_directly():
    operator = OperatorFactory(slug="byo", payment_gateway="mpesa")
    give_mpesa_keys(operator)

    gateway = get_gateway(operator)

    assert gateway.id == "mpesa"
    assert gateway.settlement == Settlement.DIRECT


def test_a_half_configured_mpesa_refuses_to_charge_rather_than_fail_at_the_customer():
    operator = OperatorFactory(slug="half", payment_gateway="mpesa")
    give_mpesa_keys(operator, passkey="")

    with pytest.raises(GatewayError, match="passkey"):
        get_gateway(operator)._client()


def test_paybill_and_till_are_different_daraja_transaction_types():
    """A till payment sent as CustomerPayBillOnline does not fail loudly — Safaricom
    rejects it in a way that looks like the customer cancelled, so the ISP blames their
    subscribers instead of their configuration."""
    from apps.payments.daraja import TRANSACTION_TYPES

    operator = OperatorFactory(slug="till", payment_gateway="mpesa")
    give_mpesa_keys(operator, collection_method="till")

    client = get_gateway(operator)._client()

    assert client.collection_method == "till"
    assert TRANSACTION_TYPES["till"] == "CustomerBuyGoodsOnline"
    assert TRANSACTION_TYPES["paybill"] == "CustomerPayBillOnline"


# --- THE INVARIANT, through the real payment path -----------------------------------------


def test_a_sale_on_the_isps_own_gateway_is_revenue_but_NEVER_withdrawable():
    """The whole finance refactor in one test. Their customer paid THEM. We hold nothing —
    so if this money ever became withdrawable, WIFI.OS would pay out cash it never
    received."""
    operator = OperatorFactory(slug="direct", payment_gateway="mpesa",
                               hotspot_commission_pct=Decimal("3.00"))
    give_mpesa_keys(operator)
    plan = PlanFactory(operator=operator, price=Decimal("100.00"))
    tx = Transaction.objects.create(
        operator=operator, plan=plan, phone="254700000001", amount=Decimal("100.00"),
        checkout_request_id="ws_CO_direct", gateway="mpesa", settlement=Settlement.DIRECT,
    )

    process_stk_callback(paid_callback("ws_CO_direct"))

    tx.refresh_from_db()
    assert tx.status == Transaction.Status.SUCCESS
    assert recorded_revenue(operator) == Decimal("100.00")  # it happened
    assert withdrawable_balance(operator) == Decimal("0.00")  # but it is not ours to pay out
    # And we did not withhold a commission from money we never held.
    assert not LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.COMMISSION
    ).exists()


def test_a_sale_on_OUR_paybill_is_withdrawable_minus_commission():
    """The aggregator path, unchanged — and it must stay working, because it is what a new
    ISP sells on."""
    operator = OperatorFactory(slug="agg", hotspot_commission_pct=Decimal("3.00"))
    plan = PlanFactory(operator=operator, price=Decimal("100.00"))
    Transaction.objects.create(
        operator=operator, plan=plan, phone="254700000001", amount=Decimal("100.00"),
        checkout_request_id="ws_CO_agg", gateway="wifios",
        settlement=Settlement.PLATFORM,
    )

    process_stk_callback(paid_callback("ws_CO_agg"))

    assert withdrawable_balance(operator) == Decimal("97.00")
    assert recorded_revenue(operator) == Decimal("100.00")


def test_the_settlement_is_frozen_on_the_transaction_not_read_from_the_operator():
    """An ISP who switches gateway must not retroactively change how yesterday's sales
    settled — that would move money between books after the fact."""
    operator = OperatorFactory(slug="switcher", hotspot_commission_pct=Decimal("0.00"))
    plan = PlanFactory(operator=operator, price=Decimal("100.00"))
    Transaction.objects.create(
        operator=operator, plan=plan, phone="254700000001", amount=Decimal("100.00"),
        checkout_request_id="ws_CO_frozen", gateway="wifios",
        settlement=Settlement.PLATFORM,
    )

    # They switch to their own gateway BEFORE the callback lands.
    operator.payment_gateway = "mpesa"
    operator.save()
    give_mpesa_keys(operator)

    process_stk_callback(paid_callback("ws_CO_frozen"))

    # The sale was TAKEN on our paybill, so it is still ours to hold and theirs to withdraw.
    assert withdrawable_balance(operator) == Decimal("100.00")


# --- the webhook ---------------------------------------------------------------------------


class TestTheWebhookCannotBeForged:
    def test_a_wrong_token_is_a_404_not_a_free_session(self, client):
        """A guessable webhook would let anybody forge a paid session and take free WiFi
        forever."""
        OperatorFactory(slug="victim", payment_gateway="mpesa")

        resp = client.post(
            "/api/v1/payments/hooks/mpesa/not-the-real-token/",
            data=paid_callback("ws_CO_x"),
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_one_isp_cannot_settle_anothers_payment_through_their_own_hook(self, client):
        """The subtle one. An ISP who learns a rival's CheckoutRequestID must not be able
        to POST it at their OWN webhook and have the sale attributed to them."""
        victim = OperatorFactory(slug="victim2", hotspot_commission_pct=Decimal("0.00"))
        attacker = OperatorFactory(slug="attacker", payment_gateway="mpesa")
        give_mpesa_keys(attacker)
        plan = PlanFactory(operator=victim, price=Decimal("100.00"))
        Transaction.objects.create(
            operator=victim, plan=plan, phone="254700000001", amount=Decimal("100.00"),
            checkout_request_id="ws_CO_victim", gateway="wifios",
            settlement=Settlement.PLATFORM,
        )

        resp = client.post(
            f"/api/v1/payments/hooks/mpesa/{attacker.webhook_token}/",
            data=paid_callback("ws_CO_victim"),
            content_type="application/json",
        )

        # We always answer 200 (a 500 makes Safaricom retry-storm us)...
        assert resp.status_code == 200
        # ...but the victim's payment was NOT settled by the attacker's hook.
        tx = Transaction.objects.get(checkout_request_id="ws_CO_victim")
        assert tx.status == Transaction.Status.PENDING
        assert withdrawable_balance(attacker) == Decimal("0.00")

    def test_a_genuine_webhook_settles_the_payment(self, client):
        operator = OperatorFactory(slug="genuine", payment_gateway="mpesa",
                                   hotspot_commission_pct=Decimal("3.00"))
        give_mpesa_keys(operator)
        plan = PlanFactory(operator=operator, price=Decimal("100.00"))
        RouterFactory(operator=operator)
        Transaction.objects.create(
            operator=operator, plan=plan, phone="254700000001", amount=Decimal("100.00"),
            checkout_request_id="ws_CO_ok", gateway="mpesa", settlement=Settlement.DIRECT,
        )

        resp = client.post(
            f"/api/v1/payments/hooks/mpesa/{operator.webhook_token}/",
            data=paid_callback("ws_CO_ok"),
            content_type="application/json",
        )

        assert resp.status_code == 200
        tx = Transaction.objects.get(checkout_request_id="ws_CO_ok")
        assert tx.status == Transaction.Status.SUCCESS
        assert tx.mpesa_receipt == "QWE123"
        # Direct: recorded, but not ours to pay out.
        assert recorded_revenue(operator) == Decimal("100.00")
        assert withdrawable_balance(operator) == Decimal("0.00")


# --- the settings API ------------------------------------------------------------------------


def test_credentials_are_never_returned_and_are_encrypted_at_rest():
    """A stolen Daraja consumer secret lets somebody collect money in the ISP's name."""
    from django.db import connection

    operator = OperatorFactory(slug="secret")
    row = give_mpesa_keys(operator, consumer_secret="super-secret-value")

    resp = owner(operator).get(GATEWAYS_URL)

    assert resp.status_code == 200
    assert "super-secret-value" not in resp.content.decode()
    card = next(g for g in resp.json()["gateways"] if g["id"] == "mpesa")
    secret_field = next(f for f in card["fields"] if f["key"] == "consumer_secret")
    assert secret_field["set"] is True
    assert secret_field["value"] == ""
    # The shortcode is NOT a secret — it is echoed so the form is editable.
    assert next(f for f in card["fields"] if f["key"] == "shortcode")["value"] == "545500"

    with connection.cursor() as cur:
        cur.execute("SELECT secrets FROM payments_gatewaycredential WHERE id = %s", [row.pk])
        assert "super-secret-value" not in cur.fetchone()[0]


def test_the_isp_is_shown_the_webhook_url_they_must_register_with_safaricom():
    operator = OperatorFactory(slug="hooky")

    body = owner(operator).get(GATEWAYS_URL).json()

    card = next(g for g in body["gateways"] if g["id"] == "mpesa")
    assert operator.webhook_token in card["webhook_url"]
    # The managed gateway is ours — the ISP has nothing to register.
    managed = next(g for g in body["gateways"] if g["id"] == "wifios")
    assert managed["webhook_url"] == ""


def test_activating_a_gateway_with_no_credentials_is_refused():
    """Switching to a half-configured gateway would stop the ISP taking money at all —
    every customer's STK push would fail at the door."""
    operator = OperatorFactory(slug="nokeys")

    resp = owner(operator).post(f"{GATEWAYS_URL}mpesa/activate/", {}, format="json")

    assert resp.status_code == 400
    operator.refresh_from_db()
    assert operator.payment_gateway == "wifios"  # unmoved, still selling


def test_a_blank_secret_on_save_keeps_the_stored_one():
    operator = OperatorFactory(slug="blank")
    give_mpesa_keys(operator, consumer_secret="keep-me")

    resp = owner(operator).post(
        f"{GATEWAYS_URL}mpesa/",
        {"credentials": {"consumer_secret": "", "shortcode": "999999"}},
        format="json",
    )

    assert resp.status_code == 200
    stored = GatewayCredential.objects.get(operator=operator, gateway="mpesa").values
    assert stored["consumer_secret"] == "keep-me"
    assert stored["shortcode"] == "999999"


def test_unbuilt_gateways_are_shown_but_honestly_marked_unavailable():
    """Better to say "coming soon" than to offer a Configure button that leads nowhere."""
    operator = OperatorFactory(slug="soon")

    body = owner(operator).get(GATEWAYS_URL).json()

    by_id = {g["id"]: g for g in body["gateways"]}
    assert by_id["mpesa"]["available"] is True
    assert by_id["kopokopo"]["available"] is False
    assert by_id["paystack"]["available"] is False


# --- security review findings -----------------------------------------------------------


def test_the_managed_gateway_cannot_be_test_charged():
    """SECURITY: the managed gateway runs on OUR Daraja. A test charge there would let any
    ISP owner fire STK prompts at arbitrary phones on Danamo's account — a cost/harassment
    vector, and pointless (our credentials always work). Only BYO gateways are testable."""
    operator = OperatorFactory(slug="notest")

    resp = owner(operator).post(
        f"{GATEWAYS_URL}wifios/test/", {"phone": "254700000001"}, format="json"
    )

    assert resp.status_code == 400
    assert "cannot be test-charged" in resp.json()["detail"]
