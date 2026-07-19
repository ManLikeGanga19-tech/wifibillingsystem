"""Withdrawal transfer cost + paybill destination.

The ISP now BEARS the transfer cost: the wallet is still debited the full amount, but they receive
amount MINUS the cost (which is remitted to the rail — Safaricom / the bank). A quote previews it,
and a paybill withdrawal needs both the shortcode and the account to credit at it."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import Payout
from apps.billing.services import (
    WalletError,
    credit_sale,
    payout_quote,
    request_payout,
    wallet_balance,
)
from apps.core.settlement import SettlementError, set_settlement_account

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db


def _fund(operator, amount="1000.00"):
    tx = TransactionFactory(operator=operator, amount=Decimal(amount))
    operator.hotspot_commission_pct = Decimal("0.00")
    operator.save()
    credit_sale(tx)


def _owner(operator):
    return UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)


class TestQuote:
    def test_breaks_down_amount_cost_and_net(self):
        q = payout_quote(OperatorFactory(), Decimal("1000"), "mpesa")
        cost = Decimal(q["cost"])
        assert cost > 0
        assert Decimal(q["amount"]) == Decimal("1000.00")
        assert Decimal(q["net"]) == Decimal("1000.00") - cost  # skimmed from what they receive
        assert q["cost_destination"] == "Safaricom"

    def test_bank_quote_names_the_bank(self):
        assert payout_quote(OperatorFactory(), Decimal("1000"), "bank")["cost_destination"] == (
            "your bank"
        )

    def test_quote_endpoint(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(_owner(op))
        r = c.get("/api/v1/billing/payouts/quote/?amount=1000&method=mpesa")
        assert r.status_code == 200, r.content
        assert Decimal(r.json()["amount"]) == Decimal("1000.00")
        assert Decimal(r.json()["net"]) < Decimal("1000.00")


class TestNetCost:
    def test_isp_bears_the_cost_and_the_wallet_debits_the_full_amount(self):
        op = OperatorFactory()
        _fund(op, "1000")
        payout = request_payout(
            operator=op, amount=Decimal("400"), user=_owner(op),
            method="mpesa", destination={"phone": "254712345678"},
        )
        assert payout.platform_cost > 0
        assert payout.net_amount == payout.amount - payout.platform_cost
        # The wallet loses the FULL amount; the cost is skimmed from what reaches the ISP.
        assert wallet_balance(op) == Decimal("600.00")


class TestPaybillWithdrawal:
    def test_records_the_shortcode_and_account(self):
        op = OperatorFactory()
        _fund(op, "1000")
        payout = request_payout(
            operator=op, amount=Decimal("400"), user=_owner(op),
            method="paybill", destination={"paybill": "555555", "paybill_account": "WISP01"},
        )
        assert payout.method == Payout.Method.PAYBILL
        assert payout.paybill == "555555" and payout.paybill_account == "WISP01"
        assert "555555" in payout.destination and "WISP01" in payout.destination

    def test_requires_the_account_number(self):
        op = OperatorFactory()
        _fund(op, "1000")
        with pytest.raises(WalletError, match="account number"):
            request_payout(
                operator=op, amount=Decimal("400"), user=_owner(op),
                method="paybill", destination={"paybill": "555555"},  # no account
            )


class TestSettlementPaybillAccount:
    def _fresh(self):
        # No settlement yet -> a first-time set (no change-code dance).
        return OperatorFactory(
            settlement_method="", settlement_paybill="", settlement_name="",
            settlement_verified_at=None,
        )

    def test_paybill_settlement_requires_an_account(self):
        with pytest.raises(SettlementError, match="account number"):
            set_settlement_account(
                self._fresh(), method="paybill",
                settlement_paybill="555555", settlement_name="My WISP",
            )

    def test_paybill_settlement_with_account_is_complete(self):
        op = self._fresh()
        set_settlement_account(
            op, method="paybill", settlement_paybill="555555",
            settlement_paybill_account="WISP01", settlement_name="My WISP",
        )
        op.refresh_from_db()
        assert op.has_settlement_account
        assert "WISP01" in op.settlement_destination
