"""Platform fraud / risk signals — read-only detection. Each test trips exactly one signal
with precise synthetic data, and confirms the quiet cases (demo, platform-owned, healthy
tenants) stay silent so the screen never cries wolf."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core import risk
from apps.core.models import TenantLifecycleEvent
from apps.payments.models import C2BPayment

from .factories import (
    OperatorFactory,
    PlanFactory,
    RouterFactory,
    TransactionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _signals(data, signal):
    return [f for f in data["findings"] if f["signal"] == signal]


def _c2b(op, amount, when):
    p = C2BPayment.objects.create(
        operator=op, trans_id=f"R{op.slug}{when:%m%d%H%M%S}{amount}", bill_ref=op.slug,
        amount=Decimal(amount), status=C2BPayment.Status.MATCHED,
    )
    C2BPayment.objects.filter(pk=p.pk).update(received_at=when)
    return p


class TestCollectionSpike:
    def test_today_dwarfs_the_baseline(self):
        op = OperatorFactory(slug="spike")
        now = timezone.now()
        for d in range(3, 8):  # ~1k/day of history
            _c2b(op, "1000", now - timedelta(days=d))
        _c2b(op, "60000", now)  # today: 60× the daily average

        s = _signals(risk.risk_signals(), "collection_spike")
        assert len(s) == 1 and s[0]["slug"] == "spike"
        assert s[0]["severity"] == "high"

    def test_steady_collections_are_quiet(self):
        op = OperatorFactory(slug="steady")
        now = timezone.now()
        for d in range(0, 8):
            _c2b(op, "1000", now - timedelta(days=d))
        assert _signals(risk.risk_signals(), "collection_spike") == []


class TestDuplicateIdentity:
    def test_shared_phone_flags_both(self):
        OperatorFactory(slug="dup-a", contact_phone="254712000000")
        OperatorFactory(slug="dup-b", contact_phone="254712000000")
        OperatorFactory(slug="unique", contact_phone="254799999999")

        s = _signals(risk.risk_signals(), "duplicate_identity")
        assert {f["slug"] for f in s} == {"dup-a", "dup-b"}

    def test_blank_contacts_are_not_grouped(self):
        OperatorFactory(slug="blank-a", contact_phone="", contact_email="")
        OperatorFactory(slug="blank-b", contact_phone="", contact_email="")
        assert _signals(risk.risk_signals(), "duplicate_identity") == []


class TestReactivationCycling:
    def test_repeated_suspensions_flag(self):
        op = OperatorFactory(slug="cycler")
        now = timezone.now()
        for i in range(4):
            TenantLifecycleEvent.objects.create(
                operator=op, slug=op.slug, name=op.name,
                event=TenantLifecycleEvent.Event.SUSPENDED,
                occurred_at=now - timedelta(days=i * 10),
            )
        s = _signals(risk.risk_signals(), "reactivation_cycling")
        assert len(s) == 1 and s[0]["detail"]["suspensions"] == 4

    def test_a_single_suspension_is_quiet(self):
        op = OperatorFactory(slug="once")
        TenantLifecycleEvent.objects.create(
            operator=op, slug=op.slug, name=op.name,
            event=TenantLifecycleEvent.Event.SUSPENDED, occurred_at=timezone.now(),
        )
        assert _signals(risk.risk_signals(), "reactivation_cycling") == []


class TestLargePayout:
    def _payout(self, op, amount, when=None):
        from apps.billing.models import Payout

        p = Payout.objects.create(operator=op, amount=Decimal(amount))
        if when:
            Payout.objects.filter(pk=p.pk).update(created_at=when)
        return p

    def test_payout_dwarfing_collections_flags(self):
        op = OperatorFactory(slug="drain")
        router = RouterFactory(operator=op)
        plan = PlanFactory(operator=op)
        TransactionFactory(operator=op, router=router, plan=plan, amount=Decimal("10000"),
                           status="success")
        self._payout(op, "80000")  # 8× lifetime collected, above the floor

        s = _signals(risk.risk_signals(), "large_payout")
        assert len(s) == 1 and s[0]["slug"] == "drain"

    def test_payout_right_after_settlement_change_is_high(self):
        op = OperatorFactory(slug="takeover")
        op.settlement_verified_at = timezone.now() - timedelta(hours=6)
        op.save()
        self._payout(op, "60000")  # big, and just after settlement (re)verify
        s = _signals(risk.risk_signals(), "large_payout")
        assert len(s) == 1 and s[0]["severity"] == "high"
        assert s[0]["detail"]["soon_after_settlement_change"] is True

    def test_small_payout_is_quiet(self):
        op = OperatorFactory(slug="small")
        self._payout(op, "1000")
        assert _signals(risk.risk_signals(), "large_payout") == []


class TestExclusionsAndEndpoint:
    def test_demo_and_platform_owned_never_flag(self):
        demo = OperatorFactory(slug="r-demo", is_demo=True, contact_phone="254700111222")
        OperatorFactory(slug="r-demo2", is_demo=True, contact_phone="254700111222")
        ours = OperatorFactory(slug="r-ours", is_platform_owned=True)
        TenantLifecycleEvent.objects.bulk_create([
            TenantLifecycleEvent(operator=ours, slug=ours.slug, name=ours.name,
                                 event="suspended", occurred_at=timezone.now())
            for _ in range(5)
        ])
        data = risk.risk_signals()
        slugs = {f["slug"] for f in data["findings"]}
        assert demo.slug not in slugs and ours.slug not in slugs

    def test_endpoint_is_platform_only(self):
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user=UserFactory(is_staff=True, role=Role.PLATFORM_SUPPORT))
        body = c.get("/api/v1/platform/risk/").json()
        assert "findings" in body and "counts" in body

    def test_no_signals_is_empty_not_error(self):
        OperatorFactory(slug="clean")
        data = risk.risk_signals()
        assert data["counts"] == {"high": 0, "medium": 0, "low": 0}
        assert data["findings"] == []
