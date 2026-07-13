"""Reports and exports — the numbers an ISP runs the business on, and the CSV an
accountant reconciles against the M-Pesa statement.

The load-bearing property is tenant isolation: a report or an export must contain ONE
ISP's money and never a shilling of another's.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.payments.models import C2BPayment, Transaction

from .factories import OperatorFactory, PlanFactory, UserFactory

pytestmark = pytest.mark.django_db


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def paid_hotspot(operator, amount, *, plan_name="1 Hour", when=None):
    plan = PlanFactory(operator=operator, name=plan_name, price=Decimal(amount))
    when = when or timezone.now()
    return Transaction.objects.create(
        operator=operator, plan=plan, phone="254712345678", amount=Decimal(amount),
        status=Transaction.Status.SUCCESS, callback_received_at=when,
        checkout_request_id=f"ws_{operator.slug}_{amount}_{when.timestamp()}",
    )


class TestRevenueSummary:
    def test_totals_split_by_source_and_plan(self):
        op = OperatorFactory()
        paid_hotspot(op, "20", plan_name="1 Hour")
        paid_hotspot(op, "20", plan_name="1 Hour")
        paid_hotspot(op, "100", plan_name="1 Day")
        C2BPayment.objects.create(
            operator=op, trans_id="C1", bill_ref="ACME001", amount=Decimal("2000"),
            status=C2BPayment.Status.MATCHED,
        )

        body = owner(op).get("/api/v1/billing/reports/revenue/").json()
        assert body["hotspot_total"] == 140.0
        assert body["pppoe_total"] == 2000.0
        assert body["total"] == 2140.0
        assert body["hotspot_count"] == 3
        # by_plan, richest first: "1 Day" (100) outranks "1 Hour" (40 across 2 sales)
        by_plan = {r["plan"]: r for r in body["by_plan"]}
        assert body["by_plan"][0]["plan"] == "1 Day"
        assert by_plan["1 Hour"]["revenue"] == 40.0 and by_plan["1 Hour"]["count"] == 2

    def test_the_range_excludes_older_money(self):
        op = OperatorFactory()
        paid_hotspot(op, "50", when=timezone.now())  # today
        paid_hotspot(op, "999", when=timezone.now() - timedelta(days=90))  # long ago

        body = owner(op).get("/api/v1/billing/reports/revenue/?from=" +
                             (timezone.localdate() - timedelta(days=7)).isoformat()).json()
        assert body["hotspot_total"] == 50.0  # the 90-day-old one is outside the window

    def test_a_report_only_ever_shows_the_callers_own_money(self):
        mine = OperatorFactory(slug="mine")
        theirs = OperatorFactory(slug="theirs")
        paid_hotspot(mine, "50")
        paid_hotspot(theirs, "9999")

        body = owner(mine).get("/api/v1/billing/reports/revenue/").json()
        assert body["hotspot_total"] == 50.0  # never theirs


class TestCsvExports:
    def _csv(self, resp):
        return b"".join(resp.streaming_content).decode()

    def test_transactions_csv_has_a_header_and_the_rows(self):
        op = OperatorFactory()
        paid_hotspot(op, "20")
        resp = owner(op).get("/api/v1/billing/reports/transactions.csv")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        assert "attachment" in resp["Content-Disposition"]
        text = self._csv(resp)
        assert "Phone,Plan,Amount" in text
        assert "254712345678" in text

    def test_ledger_csv_exports(self):
        op = OperatorFactory()
        LedgerEntry.objects.create(
            operator=op, entry_type=LedgerEntry.Type.SALE, amount=Decimal("500"), memo="a sale"
        )
        text = self._csv(owner(op).get("/api/v1/billing/reports/ledger.csv"))
        assert "a sale" in text
        assert "500" in text

    def test_an_export_never_leaks_another_isps_rows(self):
        mine = OperatorFactory(slug="mine")
        theirs = OperatorFactory(slug="theirs")
        LedgerEntry.objects.create(
            operator=mine, entry_type=LedgerEntry.Type.SALE, amount=Decimal("11"), memo="MINE-ROW"
        )
        LedgerEntry.objects.create(
            operator=theirs, entry_type=LedgerEntry.Type.SALE, amount=Decimal("22"),
            memo="THEIRS-ROW",
        )
        text = self._csv(owner(mine).get("/api/v1/billing/reports/ledger.csv"))
        assert "MINE-ROW" in text
        assert "THEIRS-ROW" not in text

    def test_pppoe_payments_csv_exports(self):
        op = OperatorFactory()
        C2BPayment.objects.create(
            operator=op, trans_id="C9", bill_ref="ACME007", amount=Decimal("2000"),
            status=C2BPayment.Status.MATCHED, msisdn="254700111222",
        )
        text = self._csv(owner(op).get("/api/v1/billing/reports/pppoe-payments.csv"))
        assert "ACME007" in text
        assert "254700111222" in text


class TestAccess:
    def test_reports_need_authentication(self):
        assert APIClient().get("/api/v1/billing/reports/revenue/").status_code in (401, 403)
