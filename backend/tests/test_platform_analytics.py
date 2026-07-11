"""Platform analytics: KPIs, trend series, per-tenant P&L, cross-tenant search.

The P&L is the one that earns its keep: it answers "which ISPs actually make me
money after the M-Pesa rails take their cut" — a question no other screen can.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.services import credit_sale
from apps.billing.tariffs import collection_cost
from apps.core.models import Operator
from apps.payments.models import Transaction

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    TransactionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def platform():
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
    )
    return c


def paid_sale(operator, amount):
    """A settled hotspot sale: commission withheld, collection cost recorded."""
    tx = TransactionFactory(
        operator=operator, amount=Decimal(amount), status=Transaction.Status.SUCCESS
    )
    tx.platform_cost = collection_cost(tx.amount)
    tx.callback_received_at = tx.created_at
    tx.save(update_fields=["platform_cost", "callback_received_at"])
    credit_sale(tx)
    return tx


class TestKpis:
    def test_headline_numbers(self):
        op = OperatorFactory(hotspot_commission_pct=Decimal("3.00"))
        paid_sale(op, "1000")  # commission 30, cost 5.50

        data = platform().get("/api/v1/platform/kpis/").json()
        assert data["scope"] == "all_isps"
        assert Decimal(str(data["earnings_month"])) == Decimal("30.00")
        assert Decimal(str(data["transaction_costs_month"])) == Decimal("5.50")
        assert Decimal(str(data["net_margin_month"])) == Decimal("24.50")
        assert Decimal(str(data["gross_volume_month"])) == Decimal("1000.00")
        # commission is recurring revenue -> counts toward MRR
        assert Decimal(str(data["mrr"])) == Decimal("30.00")
        assert Decimal(str(data["arr"])) == Decimal("360.00")

    def test_revenue_split_by_stream(self):
        op = OperatorFactory(hotspot_commission_pct=Decimal("3.00"))
        paid_sale(op, "1000")
        streams = platform().get("/api/v1/platform/kpis/").json()["revenue_by_stream"]
        assert Decimal(str(streams["commission"])) == Decimal("30.00")
        assert Decimal(str(streams["setup_fee"])) == Decimal("0")

    def test_alerts_surface_work_to_do(self):
        OperatorFactory(slug="waiting", status=Operator.Status.PENDING)
        data = platform().get("/api/v1/platform/kpis/").json()
        assert data["alerts"]["pending_approvals"] == 1
        assert data["alerts"]["unmatched_payments"] == 0

    def test_unmatched_c2b_raises_an_alert(self):
        from apps.payments.c2b import process_c2b_confirmation

        process_c2b_confirmation(
            {"TransID": "ORPHAN1", "TransAmount": "500", "BillRefNumber": "NOSUCH"}
        )
        data = platform().get("/api/v1/platform/kpis/").json()
        assert data["alerts"]["unmatched_payments"] == 1

    def test_requires_platform_staff(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        assert c.get("/api/v1/platform/kpis/").status_code == 403


class TestTimeseries:
    def test_dense_series_with_zero_gaps(self):
        data = platform().get("/api/v1/platform/timeseries/?days=7").json()
        assert data["days"] == 7
        assert len(data["series"]) == 7  # gap days present as zeros, not missing
        assert all("date" in p and "net_margin" in p for p in data["series"])

    def test_todays_sale_lands_in_the_series(self):
        op = OperatorFactory(hotspot_commission_pct=Decimal("3.00"))
        paid_sale(op, "1000")
        series = platform().get("/api/v1/platform/timeseries/?days=7").json()["series"]
        today = series[-1]
        assert Decimal(str(today["gross_volume"])) == Decimal("1000.00")
        assert Decimal(str(today["earnings"])) == Decimal("30.00")

    def test_days_is_clamped(self):
        assert platform().get("/api/v1/platform/timeseries/?days=9999").json()["days"] == 365
        assert platform().get("/api/v1/platform/timeseries/?days=1").json()["days"] == 7


class TestTenantPnl:
    def test_revenue_minus_absorbed_costs(self):
        op = OperatorFactory(slug="acme", hotspot_commission_pct=Decimal("3.00"))
        paid_sale(op, "1000")  # revenue 30, cost 5.50 -> net 24.50

        data = platform().get("/api/v1/platform/tenant-pnl/").json()
        row = next(r for r in data["tenants"] if r["slug"] == "acme")
        assert Decimal(str(row["revenue"])) == Decimal("30.00")
        assert Decimal(str(row["transaction_costs"])) == Decimal("5.50")
        assert Decimal(str(row["net_margin"])) == Decimal("24.50")
        assert Decimal(str(row["gross_collected"])) == Decimal("1000.00")
        assert row["margin_pct"] == 81.7  # 24.50 / 30

    def test_totals_add_up(self):
        a = OperatorFactory(slug="a", hotspot_commission_pct=Decimal("3.00"))
        b = OperatorFactory(slug="b", hotspot_commission_pct=Decimal("3.00"))
        paid_sale(a, "1000")
        paid_sale(b, "2000")
        data = platform().get("/api/v1/platform/tenant-pnl/").json()
        rows = data["tenants"]
        assert Decimal(str(data["totals"]["net_margin"])) == sum(
            Decimal(str(r["net_margin"])) for r in rows
        )

    def test_sorted_by_net_margin(self):
        a = OperatorFactory(slug="small", hotspot_commission_pct=Decimal("3.00"))
        b = OperatorFactory(slug="big", hotspot_commission_pct=Decimal("3.00"))
        paid_sale(a, "1000")
        paid_sale(b, "20000")
        rows = platform().get("/api/v1/platform/tenant-pnl/").json()["tenants"]
        assert rows[0]["slug"] == "big"  # most profitable first

    def test_counts_only_billable_pppoe_users(self):
        from apps.pppoe.models import Client

        op = OperatorFactory(slug="bb")
        PppoeClientFactory.create_batch(3, operator=op, status=Client.Status.ACTIVE)
        PppoeClientFactory.create_batch(2, operator=op, status=Client.Status.SUSPENDED)
        rows = platform().get("/api/v1/platform/tenant-pnl/").json()["tenants"]
        row = next(r for r in rows if r["slug"] == "bb")
        assert row["pppoe_users"] == 3  # suspended are not billed, so not counted


class TestTenantDetail:
    def test_detail_stats(self):
        op = OperatorFactory(slug="acme", hotspot_commission_pct=Decimal("3.00"))
        paid_sale(op, "1000")
        PppoeClientFactory(operator=op, status="active")

        data = platform().get(f"/api/v1/platform/tenants/{op.id}/detail_stats/").json()
        assert data["tenant"]["slug"] == "acme"
        assert Decimal(str(data["finance"]["platform_revenue"])) == Decimal("30.00")
        assert Decimal(str(data["finance"]["wallet_balance"])) == Decimal("970.00")
        assert data["usage"]["pppoe_billable"] == 1
        assert isinstance(data["recent_activity"], list)


class TestCrossTenantSearch:
    def test_finds_a_payment_by_mpesa_receipt_across_isps(self):
        op = OperatorFactory(slug="acme")
        tx = TransactionFactory(
            operator=op, status=Transaction.Status.SUCCESS, mpesa_receipt="QWE123XYZ"
        )
        data = platform().get("/api/v1/platform/search/?q=QWE123XYZ").json()
        assert data["total"] >= 1
        hit = data["results"]["transactions"][0]
        assert hit["id"] == tx.id
        assert hit["tenant"] == "acme"  # always tells you whose it is

    def test_finds_a_pppoe_client_by_account_number(self):
        op = OperatorFactory(slug="bb")
        client = PppoeClientFactory(operator=op, full_name="Jane Doe")
        data = platform().get(f"/api/v1/platform/search/?q={client.account_number}").json()
        hit = data["results"]["pppoe_clients"][0]
        assert hit["account_number"] == client.account_number
        assert hit["tenant"] == "bb"

    def test_finds_an_isp_by_name(self):
        OperatorFactory(slug="homelink", name="HomeLink Networks")
        data = platform().get("/api/v1/platform/search/?q=HomeLink").json()
        assert data["results"]["tenants"][0]["slug"] == "homelink"

    def test_short_query_is_rejected(self):
        data = platform().get("/api/v1/platform/search/?q=ab").json()
        assert data["results"] == {}

    def test_tenant_staff_cannot_search_across_isps(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        assert c.get("/api/v1/platform/search/?q=anything").status_code == 403
