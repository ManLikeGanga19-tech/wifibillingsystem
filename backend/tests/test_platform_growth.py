"""Platform growth & control: the MRR-movement waterfall + tenant churn, and the owner-only
audited wallet adjustment. These pin the SaaS-metric bucketing and the safeguards."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.core.growth import mrr_movement

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db


def _platform(owner=True):
    role = Role.PLATFORM_OWNER if owner else Role.PLATFORM_SUPPORT
    c = APIClient()
    c.force_authenticate(user=UserFactory(is_staff=True, role=role))
    return c


def _commission(operator, amount, when):
    """A withheld-commission ledger line (stored NEGATIVE) dated into a given month."""
    e = LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.COMMISSION,
        amount=Decimal(amount), memo="commission",
    )
    LedgerEntry.objects.filter(pk=e.pk).update(created_at=when)  # bypass auto_now_add
    return e


class TestMrrMovement:
    def test_buckets_new_expansion_contraction_churn(self):
        now = timezone.now()
        this_month = now.replace(day=15)
        last_month = (now.replace(day=1) - timedelta(days=5)).replace(day=15)

        grew = OperatorFactory(slug="grew")
        left = OperatorFactory(slug="left")
        joined = OperatorFactory(slug="joined")
        shrank = OperatorFactory(slug="shrank")

        # last month
        _commission(grew, "-1000", last_month)
        _commission(left, "-1000", last_month)
        _commission(shrank, "-1000", last_month)
        # this month
        _commission(grew, "-1500", this_month)     # +500 expansion
        _commission(joined, "-800", this_month)     # 800 new
        _commission(shrank, "-600", this_month)     # -400 contraction
        # `left` has nothing this month -> churned 1000

        cur = mrr_movement(months=1)["months"][-1]
        assert cur["new"] == Decimal("800")
        assert cur["expansion"] == Decimal("500")
        assert cur["contraction"] == Decimal("400")
        assert cur["churned"] == Decimal("1000")
        assert cur["net"] == Decimal("800") + Decimal("500") - Decimal("400") - Decimal("1000")
        assert cur["new_tenants"] == 1
        assert cur["churned_tenants"] == 1
        # 3 tenants were paying at the start (grew, left, shrank); 1 churned
        assert cur["tenant_churn_rate"] == round(1 / 3, 4)

    def test_demo_tenant_is_excluded(self):
        now = timezone.now().replace(day=15)
        real = OperatorFactory(slug="real-mrr")
        demo = OperatorFactory(slug="demo-mrr", is_demo=True)
        _commission(real, "-1000", now)
        _commission(demo, "-9999", now)

        cur = mrr_movement(months=1)["months"][-1]
        assert cur["mrr"] == Decimal("1000")  # demo's 9999 is invisible

    def test_endpoint_is_platform_only(self):
        body = _platform().get("/api/v1/platform/mrr-movement/?months=3").json()
        assert len(body["months"]) == 3
        assert "movers" in body


class TestWalletAdjustment:
    def test_owner_can_credit_and_debit(self):
        op = OperatorFactory(slug="adj")
        c = _platform()

        r = c.post(f"/api/v1/platform/tenants/{op.id}/adjust/",
                   {"amount": "500", "reason": "goodwill"}, format="json")
        assert r.status_code == 201, r.content
        r = c.post(f"/api/v1/platform/tenants/{op.id}/adjust/",
                   {"amount": "-200", "reason": "correction"}, format="json")
        assert r.status_code == 201

        entries = LedgerEntry.objects.filter(
            operator=op, entry_type=LedgerEntry.Type.ADJUSTMENT
        )
        assert entries.count() == 2
        assert sum(e.amount for e in entries) == Decimal("300")

    def test_reason_is_required(self):
        op = OperatorFactory(slug="adj2")
        r = _platform().post(f"/api/v1/platform/tenants/{op.id}/adjust/",
                             {"amount": "500", "reason": "  "}, format="json")
        assert r.status_code == 400

    def test_zero_amount_is_rejected(self):
        op = OperatorFactory(slug="adj3")
        r = _platform().post(f"/api/v1/platform/tenants/{op.id}/adjust/",
                             {"amount": "0", "reason": "x"}, format="json")
        assert r.status_code == 400

    def test_support_cannot_adjust(self):
        op = OperatorFactory(slug="adj4")
        r = _platform(owner=False).post(
            f"/api/v1/platform/tenants/{op.id}/adjust/",
            {"amount": "500", "reason": "nope"}, format="json",
        )
        assert r.status_code == 403
        assert not LedgerEntry.objects.filter(
            operator=op, entry_type=LedgerEntry.Type.ADJUSTMENT
        ).exists()
