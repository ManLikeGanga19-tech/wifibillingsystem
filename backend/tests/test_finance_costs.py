"""Transaction-cost tariffs and the true-margin reconciliation. The platform
absorbs M-Pesa/bank costs; reconciliation must show gross fees, those costs, and
the net margin after them."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry, PlatformLedgerEntry
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


class TestDefaultPppoeRate:
    """Default is GRADUATED 40 / 35 / 30 — small ISPs 40, large blend down to 30.
    Danamo absorbs collection costs, so gross != net and this rate has outsized
    leverage on true margin."""

    def test_small_isp_pays_top_rate(self):
        assert pppoe_user_fee_total(300) == Decimal("12000.00")  # 300 * 40
        assert pppoe_blended_rate(300) == Decimal("40.00")

    def test_spans_two_tiers(self):
        # 800 = 500*40 + 300*35 = 20000 + 10500
        assert pppoe_user_fee_total(800) == Decimal("30500.00")

    def test_large_isp_blends_to_centipid_rate(self):
        # 5000 = 500*40 + 1500*35 + 3000*30 = 20000 + 52500 + 90000
        assert pppoe_user_fee_total(5000) == Decimal("162500.00")
        # blended 32.50/user == Centipid's ~$0.25 — the big accounts get the
        # market rate while small/mid protect our margin
        assert pppoe_blended_rate(5000) == Decimal("32.50")

    def test_monotonic_no_cliff(self):
        # graduated brackets: the bill never falls as an ISP adds users
        prev = Decimal("-1")
        for n in (0, 1, 499, 500, 501, 1999, 2000, 2001, 10000):
            cur = pppoe_user_fee_total(n)
            assert cur >= prev
            prev = cur

    def test_blended_rate_falls_with_scale(self):
        # the growth incentive: your rate improves as you grow
        assert pppoe_blended_rate(300) > pppoe_blended_rate(1000)
        assert pppoe_blended_rate(1000) > pppoe_blended_rate(5000)

    def test_custom_flat_rate_overrides_default(self):
        op = OperatorFactory(pppoe_user_fee=Decimal("25.00"))
        assert pppoe_user_fee_total(5000, op) == Decimal("125000.00")  # 5000 * 25

    def test_charge_uses_default_rate(self):
        from apps.billing.services import charge_pppoe_user_fees
        from apps.pppoe.models import Client

        op = OperatorFactory(pppoe_user_fee=Decimal("0.00"))
        PppoeClientFactory.create_batch(3, operator=op, status=Client.Status.ACTIVE)
        assert charge_pppoe_user_fees() == 1
        fee = PlatformLedgerEntry.objects.get(operator=op, reason="pppoe_fee")
        assert fee.amount == Decimal("-120.00")  # 3 users * 40


class TestOnlyServedUsersAreBilled:
    """The ISP pays a platform fee ONLY for clients actually being served. A
    suspended client has not paid the ISP and has no internet — charging the ISP
    for them would bill them for customers earning them nothing."""

    def test_suspended_and_pending_are_not_billed(self):
        from apps.billing.services import charge_pppoe_user_fees
        from apps.pppoe.models import Client

        op = OperatorFactory(pppoe_user_fee=Decimal("0.00"))
        PppoeClientFactory.create_batch(3, operator=op, status=Client.Status.ACTIVE)
        PppoeClientFactory.create_batch(2, operator=op, status=Client.Status.SUSPENDED)
        PppoeClientFactory(operator=op, status=Client.Status.PENDING_INSTALL)
        PppoeClientFactory(operator=op, status=Client.Status.DISABLED)

        assert charge_pppoe_user_fees() == 1
        fee = PlatformLedgerEntry.objects.get(operator=op, reason="pppoe_fee")
        assert fee.amount == Decimal("-120.00")  # only the 3 ACTIVE * 40
        assert "(3 users)" in fee.memo

    def test_all_suspended_means_no_charge(self):
        from apps.billing.services import charge_pppoe_user_fees
        from apps.pppoe.models import Client

        op = OperatorFactory(pppoe_user_fee=Decimal("0.00"))
        PppoeClientFactory.create_batch(4, operator=op, status=Client.Status.SUSPENDED)
        assert charge_pppoe_user_fees() == 0
        assert not LedgerEntry.objects.filter(operator=op, entry_type="pppoe_fee").exists()

    def test_suspended_still_counts_for_capacity(self):
        """Capacity is a different question: a suspended client still occupies
        its slot on the sector, so AP utilisation must still count it."""
        from apps.pppoe.models import AccessPoint, Client, Tower

        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="S", capacity=10)
        PppoeClientFactory.create_batch(
            2, operator=op, access_point=ap, status=Client.Status.ACTIVE
        )
        PppoeClientFactory.create_batch(
            2, operator=op, access_point=ap, status=Client.Status.SUSPENDED
        )
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        row = c.get("/api/v1/pppoe/access-points/").json()["results"][0]
        assert row["client_count"] == 4  # capacity: active + suspended
        assert row["utilization"] == 40


class TestCustomTierTableOverride:
    """A negotiated tier table can be swapped in via settings without a code
    change (e.g. a bespoke enterprise deal)."""

    NEGOTIATED = [[500, "50"], [2000, "40"], [None, "30"]]

    @pytest.fixture(autouse=True)
    def _custom(self, settings):
        settings.PPPOE_USER_FEE_TIERS = self.NEGOTIATED

    def test_settings_table_replaces_default(self):
        assert pppoe_user_fee_total(300) == Decimal("15000.00")  # 300 * 50
        # 500*50 + 1500*40 + 3000*30 = 175000
        assert pppoe_user_fee_total(5000) == Decimal("175000.00")
        assert pppoe_blended_rate(5000) == Decimal("35.00")


class TestSetupFee:
    def test_charged_once_idempotent(self):
        op = OperatorFactory(setup_fee=Decimal("10000.00"))
        assert charge_setup_fee(op) is True
        assert charge_setup_fee(op) is False  # already charged
        entries = PlatformLedgerEntry.objects.filter(operator=op, reason="setup_fee")
        assert entries.count() == 1
        assert entries.first().amount == Decimal("-10000.00")

    def test_platform_owned_isp_exempt(self):
        op = OperatorFactory(setup_fee=Decimal("10000.00"), is_platform_owned=True)
        assert charge_setup_fee(op) is False
        assert not PlatformLedgerEntry.objects.filter(operator=op, reason="setup_fee").exists()

    def _platform_owner(self):
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        return c

    def test_approval_does_not_charge_setup_fee(self):
        # Self-service ISPs must not be auto-charged on approval
        from apps.core.models import Operator

        op = OperatorFactory(
            slug="selfserve", status=Operator.Status.PENDING, setup_fee=Decimal("8000.00")
        )
        resp = self._platform_owner().post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200, resp.content
        assert not PlatformLedgerEntry.objects.filter(operator=op, reason="setup_fee").exists()

    def test_charge_setup_action_bills_assisted_isp(self):
        op = OperatorFactory(slug="assisted", setup_fee=Decimal("8000.00"))
        admin = self._platform_owner()
        resp = admin.post(f"/api/v1/platform/tenants/{op.id}/charge-setup/")
        assert resp.status_code == 200, resp.content
        assert resp.json()["charged"] is True
        entry = PlatformLedgerEntry.objects.get(operator=op, reason="setup_fee")
        assert entry.amount == Decimal("-8000.00")
        # second call is a no-op (idempotent)
        resp2 = admin.post(f"/api/v1/platform/tenants/{op.id}/charge-setup/")
        assert resp2.json()["charged"] is False
        assert PlatformLedgerEntry.objects.filter(operator=op, reason="setup_fee").count() == 1


class TestBaseFeeTrial:
    def _charge(self):
        from apps.billing.services import charge_monthly_base_fees

        return charge_monthly_base_fees()

    def test_base_fee_waived_during_trial(self):
        from datetime import timedelta

        from django.utils import timezone

        OperatorFactory(
            slug="trialisp",
            base_fee=Decimal("500.00"),
            trial_ends_at=timezone.localdate() + timedelta(days=15),
        )
        assert self._charge() == 0  # still in free month
        assert not PlatformLedgerEntry.objects.filter(reason="base_fee").exists()

    def test_base_fee_charged_after_trial(self):
        from datetime import timedelta

        from django.utils import timezone

        op = OperatorFactory(
            slug="pastisp",
            base_fee=Decimal("500.00"),
            trial_ends_at=timezone.localdate() - timedelta(days=1),
        )
        assert self._charge() == 1
        entry = PlatformLedgerEntry.objects.get(operator=op, reason="base_fee")
        assert entry.amount == Decimal("-500.00")

    def test_approval_sets_one_month_trial(self):
        from apps.core.models import Operator

        op = OperatorFactory(slug="fresh", status=Operator.Status.PENDING)
        admin = APIClient()
        admin.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        resp = admin.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200, resp.content
        op.refresh_from_db()
        assert op.trial_ends_at is not None
        assert op.in_base_fee_trial() is True


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
