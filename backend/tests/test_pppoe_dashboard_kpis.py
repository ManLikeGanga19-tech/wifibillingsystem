"""The Fixed-line (PPPoE) dashboard KPI row: MRR, collections, renewals, and base movement.
PPPoE is a recurring business, so these are the numbers an ISP owner watches — proven here
so a hotspot-only dashboard can't quietly under-report the broadband book."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.analytics import pppoe_dashboard_kpis
from apps.pppoe.models import Client, Invoice
from apps.pppoe.services import provision_client, suspend_client

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


_seq = iter(range(1, 10_000))


def _invoice(client, *, amount, status, paid_at=None):
    today = timezone.localdate()
    n = next(_seq)
    # distinct period per invoice — the model is unique on (client, period_start)
    period = today.replace(day=1) - timedelta(days=31 * n)
    return Invoice.objects.create(
        operator=client.operator,
        client=client,
        number=f"INV-{n:06d}",
        period_start=period,
        period_end=period + timedelta(days=27),
        amount=Decimal(amount),
        due_date=today,
        status=status,
        paid_at=paid_at,
    )


class TestPppoeDashboardKpis:
    def test_mrr_counts_only_active_plan_prices(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op, price=Decimal("2000"))
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE)
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE)
        # a suspended line is NOT recurring revenue
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.SUSPENDED)

        k = pppoe_dashboard_kpis(op)
        assert k["mrr"] == Decimal("4000")
        assert k["active_subscribers"] == 2
        assert k["suspended"] == 1

    def test_outstanding_and_collected(self):
        op = OperatorFactory()
        c = PppoeClientFactory(operator=op, status=Client.Status.ACTIVE)
        _invoice(c, amount="2000", status=Invoice.Status.UNPAID)
        _invoice(c, amount="500", status=Invoice.Status.OVERDUE)
        _invoice(c, amount="1500", status=Invoice.Status.PAID, paid_at=timezone.now())

        k = pppoe_dashboard_kpis(op)
        assert k["outstanding"] == Decimal("2500")  # unpaid + overdue
        assert k["collected_month"] == Decimal("1500")  # paid this month

    def test_renewals_due_next_7_days(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op, price=Decimal("1000"))
        today = timezone.localdate()
        # due in 3 days -> counts; due in 20 days -> not; suspended -> not
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE,
                           next_due_date=today + timedelta(days=3))
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE,
                           next_due_date=today + timedelta(days=20))
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.SUSPENDED,
                           next_due_date=today + timedelta(days=2))

        k = pppoe_dashboard_kpis(op)
        assert k["renewals_due_7d"] == 1
        assert k["renewals_due_7d_value"] == Decimal("1000")

    def test_movement_fields_present_and_scoped(self):
        op = OperatorFactory()
        c = PppoeClientFactory(operator=op, status=Client.Status.PENDING_INSTALL)
        provision_client(c)  # ACTIVATED this month -> new
        suspend_client(c)

        k = pppoe_dashboard_kpis(op)
        assert k["new_this_month"] == 1
        assert "churn_rate" in k and "churned_this_month" in k

    def test_dashboard_endpoint_includes_pppoe_block(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op, price=Decimal("3000"))
        PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE)

        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        body = c.get("/api/v1/stats/").json()
        assert "pppoe" in body
        assert Decimal(body["pppoe"]["mrr"]) == Decimal("3000")
        assert body["pppoe"]["active_subscribers"] == 1
