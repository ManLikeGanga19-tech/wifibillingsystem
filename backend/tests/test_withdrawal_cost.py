"""Withdrawal = an AMOUNT to the VERIFIED settlement account.

The destination is never submitted with a withdrawal — it's the settlement account set
once in Settings (changing it needs an emailed code). So a withdrawal can't be redirected
to an account someone typed into the box, which would bypass that protection. The ISP
bears the transfer cost: the wallet is debited the full amount, they receive amount MINUS
the cost, and we remit it to the rail (Safaricom / the bank). M-Pesa personal, paybill and
bank are all valid destinations."""

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


def _fresh_op():
    """An operator with NO settlement account yet (so set_settlement_account is a
    first-time set, no change-code dance)."""
    return OperatorFactory(
        settlement_method="",
        settlement_paybill="",
        settlement_paybill_account="",
        settlement_name="",
        settlement_verified_at=None,
    )


def _bank_op():
    op = _fresh_op()
    set_settlement_account(
        op, method="bank", payout_bank_name="I&M Bank",
        payout_bank_account_number="0123456789", payout_bank_account_name="My WISP",
    )
    return op


def _mpesa_op():
    op = _fresh_op()
    set_settlement_account(
        op, method="mpesa", payout_phone="0712345678", settlement_name="Jane Doe"
    )
    return op


class TestQuote:
    def test_breaks_down_amount_cost_and_net(self):
        q = payout_quote(OperatorFactory(), Decimal("1000"))  # factory = paybill (M-Pesa rail)
        cost = Decimal(q["cost"])
        assert cost > 0
        assert Decimal(q["amount"]) == Decimal("1000.00")
        assert Decimal(q["net"]) == Decimal("1000.00") - cost  # skimmed from what they receive
        assert q["cost_destination"] == "Safaricom"
        assert q["has_account"] is True

    def test_bank_quote_names_the_bank(self):
        assert payout_quote(_bank_op(), Decimal("1000"))["cost_destination"] == "your bank"

    def test_quote_endpoint_needs_no_method(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(_owner(op))
        r = c.get("/api/v1/billing/payouts/quote/?amount=1000")
        assert r.status_code == 200, r.content
        assert Decimal(r.json()["amount"]) == Decimal("1000.00")
        assert Decimal(r.json()["net"]) < Decimal("1000.00")


class TestNetCost:
    def test_isp_bears_the_cost_and_the_wallet_debits_the_full_amount(self):
        op = OperatorFactory()
        _fund(op, "1000")
        payout = request_payout(operator=op, amount=Decimal("400"), user=_owner(op))
        assert payout.platform_cost > 0
        assert payout.net_amount == payout.amount - payout.platform_cost
        # The wallet loses the FULL amount; the cost is skimmed from what reaches the ISP.
        assert wallet_balance(op) == Decimal("600.00")


class TestDestinationComesFromSettlement:
    """The payout destination is ALWAYS the verified settlement account — never the request."""

    def test_paybill_settlement_is_used(self):
        op = OperatorFactory(settlement_paybill="555555", settlement_paybill_account="WISP01")
        _fund(op, "1000")
        payout = request_payout(operator=op, amount=Decimal("400"), user=_owner(op))
        assert payout.method == Payout.Method.PAYBILL
        assert payout.paybill == "555555" and payout.paybill_account == "WISP01"

    def test_mpesa_personal_settlement_is_used(self):
        op = _mpesa_op()
        _fund(op, "1000")
        payout = request_payout(operator=op, amount=Decimal("400"), user=_owner(op))
        assert payout.method == Payout.Method.MPESA
        assert payout.phone == "254712345678"

    def test_bank_settlement_is_used(self):
        op = _bank_op()
        _fund(op, "1000")
        payout = request_payout(operator=op, amount=Decimal("400"), user=_owner(op))
        assert payout.method == Payout.Method.BANK
        assert payout.bank_account_number == "0123456789"

    def test_no_settlement_account_blocks_the_withdrawal(self):
        op = _fresh_op()
        _fund(op, "1000")
        with pytest.raises(WalletError, match="payout account"):
            request_payout(operator=op, amount=Decimal("400"), user=_owner(op))


class TestSettlementAccount:
    def test_paybill_requires_an_account(self):
        with pytest.raises(SettlementError, match="account number"):
            set_settlement_account(
                _fresh_op(), method="paybill",
                settlement_paybill="555555", settlement_name="My WISP",
            )

    def test_mpesa_personal_requires_a_valid_number(self):
        with pytest.raises(SettlementError, match="M-Pesa"):
            set_settlement_account(
                _fresh_op(), method="mpesa", payout_phone="not-a-phone", settlement_name="Jane"
            )

    def test_mpesa_personal_is_complete_and_normalises_the_number(self):
        op = _fresh_op()
        set_settlement_account(
            op, method="mpesa", payout_phone="0712345678", settlement_name="Jane Doe"
        )
        op.refresh_from_db()
        assert op.has_settlement_account
        assert "M-Pesa" in op.settlement_destination
        assert op.payout_phone == "254712345678"  # normalised
