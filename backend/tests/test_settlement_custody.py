"""THE INVARIANT: an ISP may only withdraw money WIFI.OS is actually holding.

An ISP can now sell through their OWN payment gateway, in which case the subscriber's
money lands in the ISP's account and never touches ours. That sale is real revenue — it
belongs in their reports and it is the basis of the fee we invoice them — but we do not
have the cash.

If a directly-settled sale ever counted toward a withdrawable balance, WIFI.OS would pay
out money it never received, on every such sale, silently, forever. There is no louder
failure mode in this system, so it is tested from every side:

  * the ISP's own wallet
  * the payout guard itself (the door money leaves by)
  * the platform's float and "owed to ISPs" figures (what tells us we can cover a payout run)

and the flip side, which is just as important: a direct sale must NOT disappear. It is
still revenue.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry, Settlement
from apps.billing.services import (
    WalletError,
    credit_sale,
    recorded_revenue,
    request_payout,
    withdrawable_balance,
)

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db


def owner_of(operator):
    return UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)


def a_sale(operator, amount, settlement):
    """One completed sale, settled the given way."""
    tx = TransactionFactory(operator=operator, amount=Decimal(amount))
    credit_sale(tx, settlement=settlement)
    return tx


# --- the two books --------------------------------------------------------------------


def test_a_platform_sale_is_withdrawable_minus_our_commission():
    """The aggregator path, unchanged: the money is in our account, we withhold the fee,
    the rest is theirs to take."""
    operator = OperatorFactory(slug="agg", hotspot_commission_pct=Decimal("3.00"))
    a_sale(operator, "1000.00", Settlement.PLATFORM)

    assert withdrawable_balance(operator) == Decimal("970.00")
    assert recorded_revenue(operator) == Decimal("1000.00")


def test_a_direct_sale_is_revenue_but_NOT_withdrawable():
    """The whole point. They earned it; we never held it; they cannot take it from us."""
    operator = OperatorFactory(slug="byo", hotspot_commission_pct=Decimal("3.00"))
    a_sale(operator, "1000.00", Settlement.DIRECT)

    assert recorded_revenue(operator) == Decimal("1000.00")  # it happened
    assert withdrawable_balance(operator) == Decimal("0.00")  # but we are not holding it


def test_we_do_not_withhold_commission_from_money_we_never_held():
    """A commission DEBIT against a direct sale would be taken out of the unrelated
    platform-held money we do hold for them — i.e. we would pay ourselves out of somebody
    else's shilling. The fee on a direct sale is invoiced, not withheld."""
    operator = OperatorFactory(slug="byo2", hotspot_commission_pct=Decimal("3.00"))
    a_sale(operator, "1000.00", Settlement.DIRECT)

    assert not LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.COMMISSION
    ).exists()


def test_a_direct_sale_cannot_eat_platform_money_the_isp_really_has():
    """Belt and braces on the above: an ISP holding real platform cash must still be able
    to withdraw all of it after making direct sales."""
    operator = OperatorFactory(slug="mixed", hotspot_commission_pct=Decimal("3.00"))
    a_sale(operator, "1000.00", Settlement.PLATFORM)  # -> 970 withdrawable
    a_sale(operator, "5000.00", Settlement.DIRECT)  # -> not ours

    assert withdrawable_balance(operator) == Decimal("970.00")
    assert recorded_revenue(operator) == Decimal("6000.00")


# --- the door money leaves by ----------------------------------------------------------


def test_a_payout_CANNOT_be_funded_by_a_direct_sale():
    """THE test. If this ever passes money out, WIFI.OS is paying real cash for a sale it
    never received a shilling of."""
    operator = OperatorFactory(slug="thief", hotspot_commission_pct=Decimal("3.00"))
    a_sale(operator, "50000.00", Settlement.DIRECT)

    with pytest.raises(WalletError, match="exceeds"):
        request_payout(
            operator=operator,
            amount=Decimal("1000.00"),
            user=owner_of(operator),
            method="mpesa",
            destination={"phone": "254700000001"},
        )

    assert not LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.PAYOUT
    ).exists()


def test_a_payout_may_take_exactly_what_we_hold_and_not_one_shilling_more():
    operator = OperatorFactory(slug="edge", hotspot_commission_pct=Decimal("0.00"))
    a_sale(operator, "1000.00", Settlement.PLATFORM)
    a_sale(operator, "9000.00", Settlement.DIRECT)  # tempting, but not ours

    # One shilling over the platform-held balance is refused...
    with pytest.raises(WalletError, match="exceeds"):
        request_payout(
            operator=operator,
            amount=Decimal("1000.01"),
            user=owner_of(operator),
            method="mpesa",
            destination={"phone": "254700000001"},
        )

    # ...and exactly the held amount is allowed.
    payout = request_payout(
        operator=operator,
        amount=Decimal("1000.00"),
        user=owner_of(operator),
        method="mpesa",
        destination={"phone": "254700000001"},
    )

    assert payout.amount == Decimal("1000.00")
    assert withdrawable_balance(operator) == Decimal("0.00")


def test_the_payout_hold_itself_is_platform_money():
    """The debit that reserves the funds must sit in the same book it drew from, or the
    balance would not go down."""
    operator = OperatorFactory(slug="hold", hotspot_commission_pct=Decimal("0.00"))
    a_sale(operator, "1000.00", Settlement.PLATFORM)

    request_payout(
        operator=operator,
        amount=Decimal("500.00"),
        user=owner_of(operator),
        method="mpesa",
        destination={"phone": "254700000001"},
    )

    debit = LedgerEntry.objects.get(operator=operator, entry_type=LedgerEntry.Type.PAYOUT)
    assert debit.settlement == Settlement.PLATFORM
    assert withdrawable_balance(operator) == Decimal("500.00")


# --- what the platform believes it is holding -------------------------------------------


class TestThePlatformsOwnBooks:
    """These numbers are what tell Danamo it can cover a payout run. Inflating them with
    money that went straight to an ISP is how a platform discovers it is insolvent on the
    day everybody withdraws at once."""

    def platform_client(self):
        from apps.core.models import Operator

        platform_op = Operator.objects.filter(is_platform_owned=True).first() or (
            OperatorFactory(slug="danamo", is_platform_owned=True)
        )
        client = APIClient()
        client.force_authenticate(
            user=UserFactory(
                operator=platform_op, is_staff=True, role=Role.PLATFORM_OWNER
            )
        )
        return client

    def test_float_held_excludes_directly_settled_money(self):
        operator = OperatorFactory(slug="float-isp", hotspot_commission_pct=Decimal("0.00"))
        a_sale(operator, "1000.00", Settlement.PLATFORM)
        a_sale(operator, "9000.00", Settlement.DIRECT)

        body = self.platform_client().get("/api/v1/platform/kpis/").json()

        # We hold the 1,000. We never saw the 9,000.
        assert Decimal(str(body["float_held"])) == Decimal("1000.00")

    def test_reconciliation_reports_direct_money_separately_and_never_as_collected(self):
        operator = OperatorFactory(slug="recon-isp", hotspot_commission_pct=Decimal("0.00"))
        a_sale(operator, "1000.00", Settlement.PLATFORM)
        a_sale(operator, "9000.00", Settlement.DIRECT)

        body = self.platform_client().get("/api/v1/platform/reconciliation/").json()

        assert Decimal(str(body["total_collected"])) == Decimal("1000.00")
        assert Decimal(str(body["settled_direct_to_isps"])) == Decimal("9000.00")
        # We cannot owe an ISP money that went straight into their own account.
        assert Decimal(str(body["owed_to_isps"])) == Decimal("1000.00")


# --- the backfill ------------------------------------------------------------------------


def test_ledger_entries_default_to_platform_custody():
    """Every entry written before ISPs could bring their own gateway WAS platform-held —
    the money passed through us. The default encodes that, so the migration needed no data
    rewrite and no historical balance moved."""
    operator = OperatorFactory(slug="legacy")
    entry = LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.SALE, amount=Decimal("100.00")
    )

    assert entry.settlement == Settlement.PLATFORM
    assert withdrawable_balance(operator) == Decimal("100.00")


def test_a_replayed_callback_still_credits_only_once_whatever_the_settlement():
    """Safaricom retries. Idempotency must not have been broken by the new field."""
    operator = OperatorFactory(slug="replay", hotspot_commission_pct=Decimal("0.00"))
    tx = TransactionFactory(operator=operator, amount=Decimal("500.00"))

    credit_sale(tx, settlement=Settlement.DIRECT)
    credit_sale(tx, settlement=Settlement.DIRECT)
    credit_sale(tx, settlement=Settlement.DIRECT)

    assert LedgerEntry.objects.filter(operator=operator, transaction=tx).count() == 1
    assert recorded_revenue(operator) == Decimal("500.00")
