"""RBAC + fail-closed tenant scoping.

The regression these lock down: a platform admin with no tenant selected used to
receive EVERY tenant's data unfiltered (transactions, vouchers, dashboard), because
the scoping helper skipped filtering when the operator was None.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.billing.services import charge_monthly_base_fees, credit_sale, wallet_balance
from apps.core.models import Operator
from apps.payments.models import Transaction

from .factories import (
    OperatorFactory,
    PlanFactory,
    TransactionFactory,
    UserFactory,
    VoucherFactory,
)

pytestmark = pytest.mark.django_db

# Staff-only ISP endpoints: must 403 without a tenant.
TENANT_ENDPOINTS = [
    "/api/v1/stats/",
    "/api/v1/nav/",
    "/api/v1/payments/transactions/",
    "/api/v1/vouchers/",
    "/api/v1/sessions/",
    "/api/v1/routers/",
    "/api/v1/subscribers/",
    "/api/v1/billing/wallet/",
    "/api/v1/billing/ledger/",
    "/api/v1/operator/settings/",
    "/api/v1/ops/tickets/",
]


def plan_names(client, **kwargs):
    return [p["name"] for p in client.get("/api/v1/plans/", **kwargs).json()["results"]]


def client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def two_isps(db):
    a = OperatorFactory(slug="isp-a", name="ISP A", status=Operator.Status.ACTIVE)
    b = OperatorFactory(slug="isp-b", name="ISP B", status=Operator.Status.ACTIVE)
    # Give each some data
    PlanFactory(operator=a, name="A Plan")
    PlanFactory(operator=b, name="B Plan")
    TransactionFactory(operator=a)
    TransactionFactory(operator=b)
    VoucherFactory(operator=a)
    VoucherFactory(operator=b)
    return a, b


class TestNoCrossTenantLeak:
    def test_homeless_platform_user_gets_403_not_everything(self, two_isps):
        """THE REGRESSION: platform staff with no ISP selected must be refused,
        never handed every tenant's rows."""
        platform = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        client = client_for(platform)
        for url in TENANT_ENDPOINTS:
            resp = client.get(url)
            assert resp.status_code == 403, f"{url} returned {resp.status_code}, expected 403"
        # /plans/ is dual-purpose (public portal), so it fails closed with an
        # EMPTY list rather than 403 — but it must never list another ISP's plans.
        assert plan_names(client) == []

    def test_platform_user_acting_as_tenant_sees_only_that_tenant(self, two_isps):
        platform = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        client = client_for(platform)
        client.credentials(HTTP_X_ACT_AS_TENANT="isp-a")

        names = plan_names(client)
        assert "A Plan" in names and "B Plan" not in names
        assert client.get("/api/v1/payments/transactions/").json()["count"] == 1
        assert client.get("/api/v1/vouchers/").json()["count"] == 1

    def test_tenant_staff_cannot_view_as_another_tenant(self, two_isps):
        """A tenant user sending the platform's view-as header stays in their own ISP."""
        isp_a, _ = two_isps
        staff = UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_OWNER)
        client = client_for(staff)
        client.credentials(HTTP_X_ACT_AS_TENANT="isp-b")  # attempt to cross over

        names = plan_names(client)
        assert "A Plan" in names and "B Plan" not in names
        assert client.get("/api/v1/payments/transactions/").json()["count"] == 1

    def test_platform_owner_with_home_isp_defaults_to_it(self, two_isps):
        """Daniel: platform owner who also runs his own WISP. No header -> his ISP."""
        isp_a, _ = two_isps
        daniel = UserFactory(
            operator=isp_a, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        client = client_for(daniel)
        names = plan_names(client)
        assert "A Plan" in names and "B Plan" not in names
        # ...and he can still reach platform screens
        assert client.get("/api/v1/platform/tenants/").status_code == 200
        assert client.get("/api/v1/platform/overview/").status_code == 200

    def test_public_portal_without_context_gets_nothing(self, two_isps):
        """Fail closed: an anonymous request with no subdomain and no router must
        not receive a menu of every ISP's plans."""
        resp = APIClient().get("/api/v1/plans/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestPlatformEndpoints:
    def test_tenant_staff_locked_out_of_platform(self, two_isps):
        isp_a, _ = two_isps
        client = client_for(UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_OWNER))
        assert client.get("/api/v1/platform/tenants/").status_code == 403
        assert client.get("/api/v1/platform/overview/").status_code == 403
        assert client.get("/api/v1/billing/platform/payouts/").status_code == 403

    def test_overview_is_labelled_cross_tenant(self, two_isps):
        platform = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        data = client_for(platform).get("/api/v1/platform/overview/").json()
        assert data["scope"] == "all_isps"  # can never be mistaken for one ISP
        assert data["tenants_total"] >= 2

    def test_platform_support_is_read_only(self, two_isps):
        isp_a, _ = two_isps
        support = UserFactory(
            operator=None, is_staff=True, role=Role.PLATFORM_SUPPORT
        )
        client = client_for(support)
        assert client.get("/api/v1/platform/tenants/").status_code == 200  # may look
        resp = client.post(f"/api/v1/platform/tenants/{isp_a.id}/suspend/")
        assert resp.status_code == 403  # may not touch


class TestTenantRoles:
    def _fund(self, operator, amount="1000.00"):
        operator.hotspot_commission_pct = Decimal("0.00")
        operator.save()
        tx = TransactionFactory(operator=operator, amount=Decimal(amount))
        credit_sale(tx)

    def test_manager_cannot_withdraw(self, two_isps):
        isp_a, _ = two_isps
        self._fund(isp_a)
        manager = UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_MANAGER)
        resp = client_for(manager).post(
            "/api/v1/billing/payouts/withdraw/",
            {"amount": "200.00", "phone": "0712345678"},
            format="json",
        )
        assert resp.status_code == 403

    def test_owner_can_withdraw(self, two_isps):
        isp_a, _ = two_isps
        self._fund(isp_a)
        owner = UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_OWNER)
        resp = client_for(owner).post(
            "/api/v1/billing/payouts/withdraw/",
            {"amount": "200.00", "phone": "0712345678"},
            format="json",
        )
        assert resp.status_code == 201

    def test_support_cannot_write_anything(self, two_isps):
        isp_a, _ = two_isps
        support = UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_SUPPORT)
        client = client_for(support)
        assert client.get("/api/v1/plans/").status_code == 200  # may look
        resp = client.post(
            "/api/v1/plans/",
            {
                "name": "Sneaky Plan",
                "price": "10.00",
                "duration": "01:00:00",
                "download_kbps": 1024,
                "upload_kbps": 512,
            },
            format="json",
        )
        assert resp.status_code == 403

    def test_manager_can_run_operations(self, two_isps):
        isp_a, _ = two_isps
        manager = UserFactory(operator=isp_a, is_staff=True, role=Role.TENANT_MANAGER)
        resp = client_for(manager).post(
            "/api/v1/ops/tickets/", {"subject": "Site down", "priority": "high"}, format="json"
        )
        assert resp.status_code == 201


class TestPlatformOwnedExemption:
    def test_platform_isp_pays_no_commission(self, db):
        own = OperatorFactory(
            slug="danamo-wisp",
            is_platform_owned=True,
            hotspot_commission_pct=Decimal("3.00"),  # set, but must be ignored
            status=Operator.Status.ACTIVE,
        )
        tx = TransactionFactory(operator=own, amount=Decimal("100.00"))
        tx.status = Transaction.Status.SUCCESS
        tx.save()
        credit_sale(tx)

        assert wallet_balance(own) == Decimal("100.00")  # full amount, no 3% cut
        assert not LedgerEntry.objects.filter(
            operator=own, entry_type=LedgerEntry.Type.COMMISSION
        ).exists()  # no zero-value noise either

    def test_platform_isp_pays_no_base_fee(self, db):
        own = OperatorFactory(
            slug="danamo-wisp2",
            is_platform_owned=True,
            base_fee=Decimal("5000.00"),  # set, but must be ignored
            status=Operator.Status.ACTIVE,
        )
        paying = OperatorFactory(
            slug="paying-isp", base_fee=Decimal("1500.00"), status=Operator.Status.ACTIVE
        )
        assert charge_monthly_base_fees() == 1  # only the paying tenant
        assert wallet_balance(own) == Decimal("0.00")
        assert wallet_balance(paying) == Decimal("-1500.00")

    def test_normal_isp_still_pays_commission(self, db):
        normal = OperatorFactory(
            slug="normal-isp",
            hotspot_commission_pct=Decimal("3.00"),
            status=Operator.Status.ACTIVE,
        )
        tx = TransactionFactory(operator=normal, amount=Decimal("100.00"))
        credit_sale(tx)
        assert wallet_balance(normal) == Decimal("97.00")
