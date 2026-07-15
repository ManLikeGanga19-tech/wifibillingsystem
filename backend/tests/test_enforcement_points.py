"""The three places the ladder actually bites, and the two it must NOT.

Restricted -> no new sales (STK, vouchers), but a customer who already paid is untouched.
Locked     -> the owner's console is read-only, EXCEPT the screen where they pay us.
Always     -> reading works; paying works; auto-restore lifts everything on payment.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing import platform_account as pa
from apps.billing.models import PlatformLedgerEntry
from apps.payments.services import ProvisioningUnavailable, initiate_stk_push
from apps.vouchers.services import VoucherError, generate_batch

from .factories import (
    OperatorFactory,
    PlanFactory,
    RouterFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def push_into_lockout(operator):
    """Owe far past the lock line (limit floor 2,000 -> lock at 3,000)."""
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    pa.accrue_fee(operator, Decimal("9000.00"),
                  reason=PlatformLedgerEntry.Reason.BASE_FEE, memo="deep debt")


def restrict(operator):
    """Owe past the restrict line but below lock (2,000 < owed < 3,000)."""
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    pa.accrue_fee(operator, Decimal("2500.00"),
                  reason=PlatformLedgerEntry.Reason.BASE_FEE, memo="restrict debt")


# --- restrict: no new sales -------------------------------------------------------------


def test_a_restricted_isp_cannot_take_a_new_stk_payment():
    operator = OperatorFactory(slug="norestrict")
    RouterFactory(operator=operator)
    plan = PlanFactory(operator=operator, price=Decimal("100.00"))
    restrict(operator)

    with pytest.raises(ProvisioningUnavailable, match="settle"):
        initiate_stk_push(phone="254700000001", plan=plan)


def test_a_restricted_isp_cannot_mint_new_vouchers():
    operator = OperatorFactory(slug="novouch")
    plan = PlanFactory(operator=operator)
    restrict(operator)

    with pytest.raises(VoucherError, match="paused"):
        generate_batch(operator=operator, plan=plan, count=5)


def test_an_isp_in_good_standing_sells_normally():
    operator = OperatorFactory(slug="good")
    plan = PlanFactory(operator=operator)

    batch = generate_batch(operator=operator, plan=plan, count=3)
    assert len(batch) == 3


def test_paying_down_re_enables_sales_immediately():
    """Auto-restore at the sales gate: no job, just the next request."""
    operator = OperatorFactory(slug="restore")
    plan = PlanFactory(operator=operator)
    restrict(operator)
    with pytest.raises(VoucherError):
        generate_batch(operator=operator, plan=plan, count=1)

    pa.grant(operator, Decimal("2500.00"), memo="paid")  # clears the debt

    batch = generate_batch(operator=operator, plan=plan, count=1)
    assert len(batch) == 1


# --- lock: read-only + pay --------------------------------------------------------------


def test_a_locked_console_can_still_READ():
    operator = OperatorFactory(slug="lockread")
    push_into_lockout(operator)

    resp = owner(operator).get("/api/v1/plans/")

    assert resp.status_code == 200  # looking is always allowed


def test_a_locked_console_cannot_WRITE():
    operator = OperatorFactory(slug="lockwrite")
    push_into_lockout(operator)

    resp = owner(operator).post(
        "/api/v1/plans/",
        {"name": "New", "price": "10.00", "duration": "01:00:00",
         "download_kbps": 1024, "upload_kbps": 512},
        format="json",
    )

    assert resp.status_code == 403  # money/load actions are blocked


def test_a_locked_isp_can_STILL_PAY_us():
    """THE catch-22 guard. The one screen that clears the debt must never be locked."""
    operator = OperatorFactory(slug="lockpay")
    push_into_lockout(operator)

    # The platform-account / top-up views must remain reachable.
    resp = owner(operator).get("/api/v1/billing/account/")
    assert resp.status_code == 200


def test_paying_unlocks_the_console():
    operator = OperatorFactory(slug="unlock")
    push_into_lockout(operator)
    assert owner(operator).post(
        "/api/v1/plans/",
        {"name": "X", "price": "10.00", "duration": "01:00:00",
         "download_kbps": 1, "upload_kbps": 1},
        format="json",
    ).status_code == 403

    pa.grant(operator, Decimal("9000.00"), memo="paid up")

    ok = owner(operator).post(
        "/api/v1/plans/",
        {"name": "X", "price": "10.00", "duration": "01:00:00",
         "download_kbps": 1024, "upload_kbps": 512},
        format="json",
    )
    assert ok.status_code == 201  # full access restored, no job run


# --- the warning ------------------------------------------------------------------------


def test_a_past_due_isp_is_warned_once_and_rearmed_on_recovery():
    from apps.billing.tasks import warn_past_due_operators

    operator = OperatorFactory(slug="warn", contact_phone="254700000009")
    restrict(operator)

    warn_past_due_operators()
    operator.refresh_from_db()
    first_warned_at = operator.billing_warned_at
    assert first_warned_at is not None

    # Same fall -> the timestamp does not move (no second nag).
    warn_past_due_operators()
    operator.refresh_from_db()
    assert operator.billing_warned_at == first_warned_at

    # Recover -> the flag clears, so the NEXT fall would warn again.
    pa.grant(operator, Decimal("2500.00"))
    warn_past_due_operators()
    operator.refresh_from_db()
    assert operator.billing_warned_at is None
