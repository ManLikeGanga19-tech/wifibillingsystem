"""All platform fees now live on the platform account, and 'what you owe' nets against the
wallet. Two things this must get right:

  * a DIRECT sale's commission is a real, tracked debt — nothing goes unnoticed;
  * an AGGREGATOR ISP's economics do NOT change — we still take our cut from money we hold,
    and they can still withdraw exactly what they could before.

The netting (a pure read) replaces what a nightly wallet->platform sweep would do, so it is
tested from both sides: the direct ISP who owes, and the aggregator ISP who does not.
"""

from decimal import Decimal

import pytest

from apps.billing import platform_account as pa
from apps.billing.models import LedgerEntry, PlatformLedgerEntry, Settlement
from apps.billing.services import (
    WalletError,
    amount_owed,
    available_to_withdraw,
    charge_monthly_base_fees,
    charge_pppoe_user_fees,
    credit_sale,
    request_payout,
    withdrawable_balance,
)

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db


def owner_of(operator):
    from apps.accounts.models import Role

    return UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)


def zero_account(operator):
    """Every operator is born with a welcome credit (+KES 200). Tests asserting an EXACT
    owed figure have to start from a clean zero."""
    PlatformLedgerEntry.objects.filter(operator=operator).delete()


def a_sale(operator, amount, settlement):
    tx = TransactionFactory(operator=operator, amount=Decimal(amount))
    credit_sale(tx, settlement=settlement)
    return tx


# --- direct commission is now a tracked debt ---------------------------------------------


def test_a_direct_sale_accrues_its_commission_as_platform_debt():
    """The money went to the ISP, so we could not withhold — but the fee is not forgotten.
    It lands on the platform account, live, for the invoice and the exposure check."""
    operator = OperatorFactory(slug="direct", hotspot_commission_pct=Decimal("3.00"))
    zero_account(operator)

    a_sale(operator, "1000.00", Settlement.DIRECT)

    fee = PlatformLedgerEntry.objects.get(
        operator=operator, reason=PlatformLedgerEntry.Reason.COMMISSION
    )
    assert fee.amount == Decimal("-30.00")  # 3% of 1,000
    assert amount_owed(operator) == Decimal("30.00")  # no wallet to cover it


def test_the_direct_commission_is_charged_once_per_sale_even_on_a_replayed_callback():
    operator = OperatorFactory(slug="replay", hotspot_commission_pct=Decimal("3.00"))
    tx = TransactionFactory(operator=operator, amount=Decimal("1000.00"))

    credit_sale(tx, settlement=Settlement.DIRECT)
    credit_sale(tx, settlement=Settlement.DIRECT)  # Safaricom replays
    credit_sale(tx, settlement=Settlement.DIRECT)

    assert PlatformLedgerEntry.objects.filter(
        operator=operator, reason=PlatformLedgerEntry.Reason.COMMISSION, transaction=tx
    ).count() == 1


def test_an_aggregator_sale_still_withholds_at_source_and_owes_nothing():
    """Unchanged economics: we take our 3% from the cash we hold, so there is no debt."""
    operator = OperatorFactory(slug="agg", hotspot_commission_pct=Decimal("3.00"))

    a_sale(operator, "1000.00", Settlement.PLATFORM)

    assert withdrawable_balance(operator) == Decimal("970.00")
    assert amount_owed(operator) == Decimal("0.00")
    # The commission is a WALLET entry (withheld), NOT a platform-account debt.
    assert not PlatformLedgerEntry.objects.filter(
        operator=operator, reason=PlatformLedgerEntry.Reason.COMMISSION
    ).exists()


# --- the netting: aggregator economics must not change ------------------------------------


def test_an_aggregator_isp_with_a_wallet_owes_nothing_even_with_fees():
    """We hold their money, so a base/PPPoE fee is simply covered — no debt, and their
    available-to-withdraw drops by exactly the fee. This is what the old wallet debit did,
    now expressed by netting instead of a sweep."""
    operator = OperatorFactory(slug="covered", base_fee=Decimal("500.00"),
                               hotspot_commission_pct=Decimal("0.00"))
    zero_account(operator)
    a_sale(operator, "5000.00", Settlement.PLATFORM)
    pa.accrue_fee(operator, Decimal("500.00"),
                  reason=PlatformLedgerEntry.Reason.BASE_FEE, period="2026-07")

    assert amount_owed(operator) == Decimal("0.00")  # wallet covers it
    # 5000 held, 500 owed -> 4500 withdrawable
    assert available_to_withdraw(operator) == Decimal("4500.00")


def test_a_payout_is_capped_at_available_after_what_they_owe():
    """You cannot withdraw money we are keeping to cover your unpaid fee."""
    operator = OperatorFactory(slug="cap", hotspot_commission_pct=Decimal("0.00"))
    zero_account(operator)
    a_sale(operator, "1000.00", Settlement.PLATFORM)
    pa.accrue_fee(operator, Decimal("300.00"),
                  reason=PlatformLedgerEntry.Reason.BASE_FEE, period="2026-07")

    # 1000 held - 300 owed = 700 available. One shilling more is refused.
    with pytest.raises(WalletError, match="available"):
        request_payout(
            operator=operator, amount=Decimal("700.01"), user=owner_of(operator),
            method="mpesa", destination={"phone": "254700000001"},
        )
    payout = request_payout(
        operator=operator, amount=Decimal("700.00"), user=owner_of(operator),
        method="mpesa", destination={"phone": "254700000001"},
    )
    assert payout.amount == Decimal("700.00")


def test_a_direct_isps_debt_is_not_hidden_by_someone_elses_wallet():
    """Netting is per-operator. A direct ISP owes their fee outright."""
    other = OperatorFactory(slug="rich")
    a_sale(other, "100000.00", Settlement.PLATFORM)  # somebody else's fat wallet

    operator = OperatorFactory(slug="poor", hotspot_commission_pct=Decimal("3.00"))
    zero_account(operator)
    a_sale(operator, "1000.00", Settlement.DIRECT)

    assert amount_owed(operator) == Decimal("30.00")


# --- fees route to the platform account, not the wallet ----------------------------------


def test_base_fee_lands_on_the_platform_account_not_the_wallet():
    operator = OperatorFactory(slug="basefee", base_fee=Decimal("500.00"))

    assert charge_monthly_base_fees() >= 1

    assert PlatformLedgerEntry.objects.filter(
        operator=operator, reason=PlatformLedgerEntry.Reason.BASE_FEE
    ).exists()
    # The wallet (custody) is untouched by the fee.
    assert not LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.BASE_FEE
    ).exists()


def test_base_fee_is_charged_once_per_month():
    operator = OperatorFactory(slug="once", base_fee=Decimal("500.00"))

    charge_monthly_base_fees()
    charge_monthly_base_fees()  # a re-run of the beat task

    assert PlatformLedgerEntry.objects.filter(
        operator=operator, reason=PlatformLedgerEntry.Reason.BASE_FEE
    ).count() == 1


def test_platform_earnings_count_fees_from_BOTH_ledgers():
    """The platform's own P&L must not lose a fee just because it moved ledgers. A direct
    commission (platform account) and an aggregator commission (withheld in the wallet)
    both count as revenue to us."""
    from apps.billing.revenue import platform_earnings

    agg = OperatorFactory(slug="agg-earn", hotspot_commission_pct=Decimal("3.00"))
    a_sale(agg, "1000.00", Settlement.PLATFORM)  # 30 withheld in the wallet

    direct = OperatorFactory(slug="direct-earn", hotspot_commission_pct=Decimal("3.00"))
    a_sale(direct, "2000.00", Settlement.DIRECT)  # 60 accrued on the platform account

    # 30 (withheld) + 60 (accrued) = 90, seen across both ledgers.
    assert platform_earnings(operator=agg) == Decimal("30.00")
    assert platform_earnings(operator=direct) == Decimal("60.00")


def test_pppoe_and_base_fees_add_up_into_one_owed_number():
    """The whole point of routing everything to one account: a single 'what you owe'."""
    from apps.pppoe.models import Client

    from .factories import PppoeClientFactory

    operator = OperatorFactory(slug="both", base_fee=Decimal("500.00"),
                               pppoe_user_fee=Decimal("40.00"))
    zero_account(operator)
    PppoeClientFactory.create_batch(2, operator=operator, status=Client.Status.ACTIVE)

    charge_monthly_base_fees()
    charge_pppoe_user_fees()

    # 500 base + 2 x 40 = 580, all on the platform account, all owed (no wallet).
    assert pa.debt(operator) == Decimal("580.00")
    assert amount_owed(operator) == Decimal("580.00")
