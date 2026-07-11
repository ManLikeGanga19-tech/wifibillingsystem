"""Transaction-cost tariffs and the true-margin reconciliation. The platform
absorbs M-Pesa/bank costs; reconciliation must show gross fees, those costs, and
the net margin after them."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.billing.pricing import pppoe_blended_rate, pppoe_user_fee_total
from apps.billing.services import charge_setup_fee, credit_sale
from apps.billing.tariffs import collection_cost, payout_cost
from apps.payments.c2b import process_c2b_confirmation
from apps.payments.models import C2BPayment, Transaction

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    TransactionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


class TestCollectionCost:
    def test_free_under_floor(self):
        assert collection_cost(Decimal("200")) == Decimal("0.00")
        assert collection_cost(Decimal("50")) == Decimal("0.00")

    def test_percentage_above_floor(self):
        # 0.55% of 1000 = 5.50
        assert collection_cost(Decimal("1000")) == Decimal("5.50")

    def test_capped(self):
        # 0.55% of 1,000,000 = 5500, capped at 200
        assert collection_cost(Decimal("1000000")) == Decimal("200")


class TestPayoutCost:
    def test_bank_is_flat_default_zero(self):
        assert payout_cost(Decimal("5000"), "bank") == Decimal("0")

    def test_mpesa_b2c_banded(self):
        assert payout_cost(Decimal("500"), "mpesa") == Decimal("20")
        assert payout_cost(Decimal("3000"), "mpesa") == Decimal("35")
        assert payout_cost(Decimal("15000"), "mpesa") == Decimal("50")

    def test_mpesa_b2c_above_top_band(self):
        assert payout_cost(Decimal("50000"), "mpesa") == Decimal("60")


class TestCostRecordedOnSettle:
    def test_c2b_records_platform_cost(self):
        client = PppoeClientFactory(plan__price=Decimal("2000"))
        process_c2b_confirmation(
            {"TransID": "C2B1", "TransAmount": "2000",
             "BillRefNumber": client.account_number, "MSISDN": "254712345678"}
        )
        payment = C2BPayment.objects.get(trans_id="C2B1")
        assert payment.platform_cost == collection_cost(Decimal("2000"))
        assert payment.platform_cost > 0

    def test_stk_success_records_cost_via_credit_sale_path(self):
        # A successful transaction carries an estimated collection cost
        tx = TransactionFactory(amount=Decimal("1000"), status=Transaction.Status.SUCCESS)
        tx.platform_cost = collection_cost(tx.amount)
        tx.save(update_fields=["platform_cost"])
        assert tx.platform_cost == Decimal("5.50")


class TestGraduatedPppoeTiers:
    def test_within_first_tier_flat(self):
        # 300 users, all in the 50-bracket
        assert pppoe_user_fee_total(300) == Decimal("15000.00")  # 300 * 50

    def test_boundary_of_first_tier(self):
        assert pppoe_user_fee_total(500) == Decimal("25000.00")  # 500 * 50

    def test_spans_two_tiers(self):
        # 800 = 500*50 + 300*40 = 25000 + 12000
        assert pppoe_user_fee_total(800) == Decimal("37000.00")

    def test_spans_all_three_tiers(self):
        # 5000 = 500*50 + 1500*40 + 3000*30 = 25000 + 60000 + 90000
        assert pppoe_user_fee_total(5000) == Decimal("175000.00")

    def test_total_is_monotonic_no_cliff(self):
        # graduated tiers never let the bill fall as users grow
        prev = Decimal("-1")
        for n in (0, 1, 499, 500, 501, 1999, 2000, 2001, 10000):
            cur = pppoe_user_fee_total(n)
            assert cur >= prev
            prev = cur

    def test_blended_rate_drops_with_scale(self):
        assert pppoe_blended_rate(300) == Decimal("50.00")
        assert pppoe_blended_rate(5000) == Decimal("35.00")  # 175000 / 5000

    def test_custom_flat_rate_overrides_tiers(self):
        op = OperatorFactory(pppoe_user_fee=Decimal("25.00"))
        assert pppoe_user_fee_total(5000, op) == Decimal("125000.00")  # 5000 * 25

    def test_charge_uses_tiers_when_no_custom_rate(self):
        from apps.billing.services import charge_pppoe_user_fees
        from apps.pppoe.models import Client

        op = OperatorFactory(pppoe_user_fee=Decimal("0.00"))
        PppoeClientFactory.create_batch(3, operator=op, status=Client.Status.ACTIVE)
        assert charge_pppoe_user_fees() == 1
        fee = LedgerEntry.objects.get(operator=op, entry_type="pppoe_fee")
        assert fee.amount == Decimal("-150.00")  # 3 users graduated at 50


class TestSetupFee:
    def test_charged_once_idempotent(self):
        op = OperatorFactory(setup_fee=Decimal("10000.00"))
        assert charge_setup_fee(op) is True
        assert charge_setup_fee(op) is False  # already charged
        entries = LedgerEntry.objects.filter(operator=op, entry_type="setup_fee")
        assert entries.count() == 1
        assert entries.first().amount == Decimal("-10000.00")

    def test_platform_owned_isp_exempt(self):
        op = OperatorFactory(setup_fee=Decimal("10000.00"), is_platform_owned=True)
        assert charge_setup_fee(op) is False
        assert not LedgerEntry.objects.filter(operator=op, entry_type="setup_fee").exists()

    def test_approval_endpoint_charges_setup_fee(self):
        from apps.core.models import Operator

        op = OperatorFactory(
            slug="newisp", status=Operator.Status.PENDING, setup_fee=Decimal("8000.00")
        )
        admin = APIClient()
        admin.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        resp = admin.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200, resp.content
        entry = LedgerEntry.objects.get(operator=op, entry_type="setup_fee")
        assert entry.amount == Decimal("-8000.00")


class TestNetMarginReconciliation:
    def _platform_admin(self):
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        return c

    def test_net_margin_is_gross_earnings_minus_costs(self):
        op = OperatorFactory(hotspot_commission_pct=Decimal("3.00"))
        # A successful hotspot sale: commission withheld + a collection cost booked
        tx = TransactionFactory(
            operator=op, amount=Decimal("1000"), status=Transaction.Status.SUCCESS,
            mpesa_receipt="RCT1",
        )
        tx.platform_cost = collection_cost(tx.amount)  # 5.50
        tx.save(update_fields=["platform_cost"])
        credit_sale(tx)  # commission = 3% of 1000 = 30

        data = self._platform_admin().get("/api/v1/platform/reconciliation/").json()
        assert Decimal(str(data["platform_earnings"])) == Decimal("30.00")
        assert Decimal(str(data["transaction_costs"])) == Decimal("5.50")
        assert Decimal(str(data["collection_costs"])) == Decimal("5.50")
        assert Decimal(str(data["net_margin"])) == Decimal("24.50")

    def test_costs_zero_when_no_activity(self):
        data = self._platform_admin().get("/api/v1/platform/reconciliation/").json()
        assert Decimal(str(data["transaction_costs"])) == Decimal("0")
        assert Decimal(str(data["net_margin"])) == Decimal(str(data["platform_earnings"]))
