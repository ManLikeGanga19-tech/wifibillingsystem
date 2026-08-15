"""Tenant offboarding — the reversible-then-terminal removal of an ISP.

Pins the state machine (initiate → abort | complete), the money snapshot, the fact that
completion actually pulls subscribers off the router, owner-gating, and that a data export
never leaks another tenant's records."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import Operator, TenantLifecycleEvent, TenantOffboarding
from apps.core.offboarding import (
    OffboardingError,
    abort_offboarding,
    complete_offboarding,
    initiate_offboarding,
)
from apps.pppoe.models import Client

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db


def _owner():
    c = APIClient()
    c.force_authenticate(user=UserFactory(is_staff=True, role=Role.PLATFORM_OWNER))
    return c


def _support():
    c = APIClient()
    c.force_authenticate(user=UserFactory(is_staff=True, role=Role.PLATFORM_SUPPORT))
    return c


def _active_op(slug="leaving"):
    """An ACTIVE tenant with an activation anchor, like every real live tenant (the backfill
    migration guarantees one). Without it, a later reinstatement would read as a first
    activation rather than a win-back."""
    op = OperatorFactory(slug=slug, status=Operator.Status.ACTIVE)
    TenantLifecycleEvent.objects.create(
        operator=op, slug=op.slug, name=op.name,
        event=TenantLifecycleEvent.Event.ACTIVATED, to_status="active",
        occurred_at=timezone.now() - timedelta(days=120),
    )
    return op


class TestStateMachine:
    def test_initiate_freezes_and_snapshots(self):
        op = _active_op()
        ob = initiate_offboarding(op, reason="fraud", actor=None, grace_days=14)

        op.refresh_from_db()
        assert op.status == Operator.Status.SUSPENDED       # console frozen
        assert op.is_active is True                          # but NOT torn down yet
        assert ob.state == TenantOffboarding.State.SCHEDULED
        assert ob.in_grace
        assert op.lifecycle_events.filter(event="suspended").exists()

    def test_reason_is_required(self):
        op = _active_op()
        with pytest.raises(OffboardingError):
            initiate_offboarding(op, reason="  ", actor=None)

    def test_demo_and_platform_owned_refused(self):
        demo = OperatorFactory(slug="demo-off", is_demo=True)
        ours = OperatorFactory(slug="ours-off", is_platform_owned=True)
        with pytest.raises(OffboardingError):
            initiate_offboarding(demo, reason="x", actor=None)
        with pytest.raises(OffboardingError):
            initiate_offboarding(ours, reason="x", actor=None)

    def test_only_one_live_offboarding(self):
        op = _active_op()
        initiate_offboarding(op, reason="first", actor=None)
        with pytest.raises(OffboardingError):
            initiate_offboarding(op, reason="second", actor=None)

    def test_abort_reinstates(self):
        op = _active_op()
        initiate_offboarding(op, reason="mistake", actor=None)
        abort_offboarding(op, actor=None)

        op.refresh_from_db()
        assert op.status == Operator.Status.ACTIVE
        assert op.offboardings.filter(state="aborted").exists()
        assert op.lifecycle_events.filter(event="reactivated").exists()

    def test_complete_blocked_in_grace_unless_forced(self):
        op = _active_op()
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=14)
        with pytest.raises(OffboardingError):
            complete_offboarding(op, actor=None)  # still in grace, not forced

    def test_complete_tears_down_service_and_is_terminal(self):
        op = _active_op()
        c1 = PppoeClientFactory(operator=op, status=Client.Status.ACTIVE)
        c2 = PppoeClientFactory(operator=op, status=Client.Status.SUSPENDED)
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=14)

        ob = complete_offboarding(op, actor=None, force=True)

        op.refresh_from_db()
        c1.refresh_from_db()
        c2.refresh_from_db()
        assert op.is_active is False                          # hard kill
        assert op.lifecycle_events.filter(event="cancelled").exists()
        assert c1.status == Client.Status.CANCELLED           # pulled off the router
        assert c2.status == Client.Status.CANCELLED
        assert ob.state == TenantOffboarding.State.COMPLETED
        assert ob.subscribers_torn_down == 2

    def test_complete_allowed_after_grace(self):
        op = _active_op()
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=14)
        ob = op.offboardings.get(state="scheduled")
        TenantOffboarding.objects.filter(pk=ob.pk).update(
            grace_until=timezone.now() - timedelta(hours=1)
        )
        complete_offboarding(op, actor=None)  # no force needed once grace elapsed
        op.refresh_from_db()
        assert op.is_active is False

    def test_cancelled_counts_as_churn(self):
        """A completed offboarding must read as a lost tenant in growth's churn stream."""
        from apps.core.growth import _live_at, _live_state_stream

        op = _active_op()
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=0)
        complete_offboarding(op, actor=None)
        stream = _live_state_stream()
        assert _live_at(stream[op.id], timezone.now()) is False


class TestEndpoints:
    def test_full_flow_over_http(self):
        op = _active_op("http-off")
        c = _owner()
        r = c.post(f"/api/v1/platform/tenants/{op.id}/offboard/",
                   {"reason": "non-payment"}, format="json")
        assert r.status_code == 201, r.content
        assert "grace_until" in r.json()

        r = c.post(f"/api/v1/platform/tenants/{op.id}/offboard-complete/",
                   {"force": True}, format="json")
        assert r.status_code == 200, r.content
        op.refresh_from_db()
        assert op.is_active is False

    def test_support_cannot_offboard(self):
        op = _active_op("support-off")
        r = _support().post(f"/api/v1/platform/tenants/{op.id}/offboard/",
                            {"reason": "nope"}, format="json")
        assert r.status_code == 403
        assert not TenantOffboarding.objects.filter(operator=op).exists()

    def test_serializer_exposes_live_offboarding(self):
        op = _active_op("ser-off")
        initiate_offboarding(op, reason="leaving", actor=None)
        body = _owner().get(f"/api/v1/platform/tenants/{op.id}/").json()
        assert body["offboarding"] is not None
        assert body["offboarding"]["reason"] == "leaving"


class TestExport:
    def test_export_is_scoped_to_one_tenant(self):
        a = _active_op("exp-a")
        b = _active_op("exp-b")
        PppoeClientFactory(operator=a, full_name="Alice Aturi")
        PppoeClientFactory(operator=b, full_name="Bob Bahati")

        body = _owner().get(f"/api/v1/platform/tenants/{a.id}/export/").json()
        names = {s["full_name"] for s in body["subscribers"]}
        assert "Alice Aturi" in names
        assert "Bob Bahati" not in names  # no cross-tenant leak

    def test_export_is_owner_only(self):
        op = _active_op("exp-perm")
        r = _support().get(f"/api/v1/platform/tenants/{op.id}/export/")
        assert r.status_code == 403


def _wallet(op, amount):
    """Give a tenant held (withdrawable) balance."""
    from apps.billing.services import adjust_wallet

    adjust_wallet(op, amount=Decimal(amount), reason="seed balance", actor=UserFactory())


def _arrears(op, amount):
    """Make a tenant owe us `amount` in unpaid platform fees (no offsetting wallet)."""
    from apps.billing.models import PlatformLedgerEntry

    PlatformLedgerEntry.objects.create(
        operator=op, reason=PlatformLedgerEntry.Reason.BASE_FEE,
        amount=-Decimal(amount), memo="fees",
    )


class TestFinalSettlement:
    def test_debt_netted_from_held_balance(self):
        from apps.billing.platform_account import debt
        from apps.billing.services import withdrawable_balance

        op = _active_op("settle-ok")
        _wallet(op, "5000")
        _arrears(op, "3000")
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=0)
        held, owed = withdrawable_balance(op), debt(op)  # held > owed here
        ob = complete_offboarding(op, actor=None)

        assert ob.fees_recovered == owed              # whole debt covered from the wallet
        assert ob.net_settlement == held - owed       # remainder paid out to the ISP
        assert ob.residual_owed == Decimal("0")
        assert withdrawable_balance(op) == held - owed  # debt actually left the wallet

    def test_shortfall_becomes_flagged_bad_debt(self):
        from apps.billing.platform_account import debt
        from apps.billing.services import withdrawable_balance
        from apps.core.risk import risk_signals

        op = _active_op("settle-baddebt")
        _wallet(op, "1000")
        _arrears(op, "9000")
        initiate_offboarding(op, reason="leaving", actor=None, grace_days=0)
        held, owed = withdrawable_balance(op), debt(op)  # held < owed here
        ob = complete_offboarding(op, actor=None)

        assert ob.fees_recovered == held              # only what we held could be recovered
        assert ob.net_settlement == Decimal("0")
        assert ob.residual_owed == owed - held        # the rest is bad debt
        s = [f for f in risk_signals()["findings"] if f["signal"] == "offboarding_bad_debt"]
        assert len(s) == 1 and s[0]["slug"] == "settle-baddebt"


class TestArrearsBlocks:
    def test_export_blocked_when_offboarding_with_arrears(self):
        op = _active_op("arrears-block")
        _arrears(op, "3000")
        initiate_offboarding(op, reason="leaving", actor=None)
        # platform export endpoint refuses
        r = _owner().get(f"/api/v1/platform/tenants/{op.id}/export/")
        assert r.status_code == 403

    def test_export_allowed_when_offboarding_without_arrears(self):
        op = _active_op("no-arrears")
        initiate_offboarding(op, reason="leaving", actor=None)
        r = _owner().get(f"/api/v1/platform/tenants/{op.id}/export/")
        assert r.status_code == 200

    def test_export_allowed_when_arrears_but_not_offboarding(self):
        from apps.core.offboarding import export_blocked_reason

        op = _active_op("arrears-only")
        _arrears(op, "3000")
        assert export_blocked_reason(op) is None  # only blocked DURING offboarding

    def test_payout_blocked_during_offboarding(self):
        from apps.billing.services import WalletError, request_payout

        op = _active_op("no-payout")
        _wallet(op, "5000")
        initiate_offboarding(op, reason="leaving", actor=None)
        with pytest.raises(WalletError):
            request_payout(operator=op, amount=Decimal("500"), user=UserFactory())
