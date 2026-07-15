"""The auto-suspension ladder: a pure function of what an ISP owes versus their limit.

Because the level is DERIVED, not stored, the most important property is auto-restore: pay
down the debt and the level drops on the very next read, with nothing to unwind. These
tests walk an ISP up every rung and back down, and check the two exemptions (Danamo's own
WISP, and a tenant still in its trial).
"""

from decimal import Decimal

import pytest

from apps.billing import enforcement as enf
from apps.billing import platform_account as pa
from apps.billing.models import PlatformLedgerEntry

from .factories import OperatorFactory

pytestmark = pytest.mark.django_db


def owe(operator, amount):
    """Put the ISP exactly `amount` in debt on the platform account (no wallet to net)."""
    PlatformLedgerEntry.objects.filter(operator=operator).delete()  # clear welcome credit
    if amount:
        pa.accrue_fee(
            operator, Decimal(amount), reason=PlatformLedgerEntry.Reason.BASE_FEE,
            memo="test debt",
        )


def a_new_isp(slug="isp"):
    """No history → credit limit is the floor, KES 2,000. So the rungs are:
    warn > 1,200 | restrict > 2,000 | lock > 3,000."""
    return OperatorFactory(slug=slug)


# --- the rungs --------------------------------------------------------------------------


def test_a_new_isp_limit_is_the_floor():
    operator = a_new_isp()
    assert enf.credit_limit(operator) == enf.CREDIT_FLOOR  # 2,000


def test_owing_nothing_is_current():
    operator = a_new_isp()
    owe(operator, 0)
    assert enf.billing_level(operator) == enf.CURRENT
    assert enf.can_sell(operator) is True
    assert enf.is_locked(operator) is False


def test_crossing_60pct_warns():
    operator = a_new_isp()
    owe(operator, "1300.00")  # > 0.6 x 2000
    assert enf.billing_level(operator) == enf.WARNED
    assert enf.can_sell(operator) is True  # warned, but still selling


def test_crossing_the_limit_restricts_new_sales():
    operator = a_new_isp()
    owe(operator, "2100.00")  # > 1.0 x 2000
    assert enf.billing_level(operator) == enf.RESTRICTED
    assert enf.can_sell(operator) is False  # THE lever: no new debt
    assert enf.is_locked(operator) is False  # console still usable


def test_crossing_150pct_locks_the_console():
    operator = a_new_isp()
    owe(operator, "3100.00")  # > 1.5 x 2000
    assert enf.billing_level(operator) == enf.LOCKED
    assert enf.is_locked(operator) is True
    assert enf.can_sell(operator) is False


# --- auto-restore: the whole point of deriving the level --------------------------------


def test_paying_down_lifts_every_restriction_with_no_job():
    operator = a_new_isp()
    owe(operator, "3100.00")
    assert enf.billing_level(operator) == enf.LOCKED

    # A top-up lands (their STK payment). Nothing else runs.
    pa.grant(operator, Decimal("3100.00"), memo="paid up")

    assert enf.billing_level(operator) == enf.CURRENT
    assert enf.can_sell(operator) is True
    assert enf.is_locked(operator) is False


def test_a_partial_payment_steps_down_one_rung():
    operator = a_new_isp()
    owe(operator, "3100.00")  # locked
    pa.grant(operator, Decimal("900.00"))  # now owes 2,200 -> restricted, not locked
    assert enf.billing_level(operator) == enf.RESTRICTED


# --- netting: a wallet balance covers the debt ------------------------------------------


def test_an_aggregator_with_a_wallet_is_not_enforced_for_a_covered_fee():
    """They owe a fee, but we hold their money — owed nets to zero, so no rung is hit."""
    from apps.billing.models import LedgerEntry, Settlement

    operator = a_new_isp("agg")
    owe(operator, "2500.00")  # would be RESTRICTED on its own
    LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.SALE, amount=Decimal("5000.00"),
        settlement=Settlement.PLATFORM,
    )  # we hold 5,000 for them

    assert enf.billing_level(operator) == enf.CURRENT


# --- the limit scales with size ---------------------------------------------------------


def test_a_bigger_isp_gets_a_bigger_limit():
    """1.5x their monthly RUN-RATE (base + per-user fees), once that beats the floor. Driven
    by their real configuration, not by how much they happen to owe."""
    from apps.pppoe.models import Client

    from .factories import PppoeClientFactory

    operator = a_new_isp("big")
    operator.base_fee = Decimal("0.00")
    operator.pppoe_user_fee = Decimal("40.00")
    operator.save()
    # 100 served users x 40 = 4,000 run-rate -> limit 6,000, not the 2,000 floor.
    PppoeClientFactory.create_batch(100, operator=operator, status=Client.Status.ACTIVE)

    assert enf.credit_limit(operator) == Decimal("6000.00")


def test_a_per_tenant_override_wins():
    operator = a_new_isp("special")
    operator.credit_limit_override = Decimal("500.00")
    operator.save()
    owe(operator, "600.00")  # over the override -> restricted

    assert enf.credit_limit(operator) == Decimal("500.00")
    assert enf.billing_level(operator) == enf.RESTRICTED


def test_a_zero_override_means_never_enforce():
    operator = a_new_isp("vip")
    operator.credit_limit_override = Decimal("0.00")
    operator.save()
    owe(operator, "999999.00")

    assert enf.billing_level(operator) == enf.CURRENT


# --- the exemptions ---------------------------------------------------------------------


def test_the_platform_owned_wisp_is_never_enforced():
    operator = OperatorFactory(slug="danamo", is_platform_owned=True)
    owe(operator, "999999.00")
    assert enf.billing_level(operator) == enf.CURRENT


def test_a_trial_isp_is_warned_but_never_cut_off():
    """Leniency during the trial: they see what is accruing, but a business that has not
    started earning is not restricted or locked."""
    from datetime import timedelta

    from django.utils import timezone

    operator = OperatorFactory(
        slug="trial", trial_ends_at=timezone.localdate() + timedelta(days=10)
    )
    owe(operator, "5000.00")  # deep into LOCKED territory on the numbers

    assert enf.billing_level(operator) == enf.WARNED  # capped
    assert enf.can_sell(operator) is True
