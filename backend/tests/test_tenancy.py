"""Tenant isolation: the security property the whole SaaS stands on."""

import pytest
from rest_framework.test import APIClient

from apps.core.models import Operator
from apps.core.tenancy import _slug_from_host

from .factories import (
    OperatorFactory,
    PlanFactory,
    RouterFactory,
    TransactionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def staff_client(operator):
    user = UserFactory(operator=operator, is_staff=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def two_tenants(db):
    op_a = OperatorFactory(slug="wisp-a", name="WISP A", status=Operator.Status.ACTIVE)
    op_b = OperatorFactory(slug="wisp-b", name="WISP B", status=Operator.Status.ACTIVE)
    return op_a, op_b


class TestSubdomainResolution:
    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("wisp-a.wifios.co.ke", "wisp-a"),
            ("wisp-a.wifios.co.ke:8000", "wisp-a"),
            ("www.wifios.co.ke", None),
            ("api.wifios.co.ke", None),
            ("wifios.co.ke", "wifios"),  # bare domain: first label isn't reserved
            ("localhost", None),
            ("localhost:8000", None),
        ],
    )
    def test_slug_extraction(self, host, expected):
        assert _slug_from_host(host) == expected


class TestTenantIsolation:
    def test_staff_only_see_their_own_plans(self, two_tenants):
        op_a, op_b = two_tenants
        PlanFactory(operator=op_a, name="A Plan")
        PlanFactory(operator=op_b, name="B Plan")

        names = [p["name"] for p in staff_client(op_a).get("/api/v1/plans/").json()["results"]]
        assert names == ["A Plan"]

    def test_staff_only_see_their_own_transactions(self, two_tenants):
        op_a, op_b = two_tenants
        TransactionFactory(operator=op_a)
        tx_b = TransactionFactory(operator=op_b)

        client_a = staff_client(op_a)
        ids = [t["id"] for t in client_a.get("/api/v1/payments/transactions/").json()["results"]]
        assert tx_b.id not in ids
        assert len(ids) == 1

    def test_cannot_touch_other_tenants_router(self, two_tenants):
        op_a, op_b = two_tenants
        router_b = RouterFactory(operator=op_b)
        resp = staff_client(op_a).get(f"/api/v1/routers/{router_b.id}/")
        assert resp.status_code == 404  # scoped queryset -> invisible, not forbidden

    def test_host_header_cannot_cross_tenants_for_staff(self, two_tenants):
        """A tenant-A token replayed against tenant-B's subdomain must stay in A."""
        op_a, op_b = two_tenants
        PlanFactory(operator=op_a, name="A Plan")
        PlanFactory(operator=op_b, name="B Plan")

        client = staff_client(op_a)
        resp = client.get("/api/v1/plans/", HTTP_HOST="wisp-b.wifios.co.ke")
        names = [p["name"] for p in resp.json()["results"]]
        assert names == ["A Plan"]

    def test_public_portal_scoped_by_subdomain(self, two_tenants):
        op_a, op_b = two_tenants
        PlanFactory(operator=op_a, name="A Plan")
        PlanFactory(operator=op_b, name="B Plan")

        resp = APIClient().get("/api/v1/plans/", HTTP_HOST="wisp-b.wifios.co.ke")
        names = [p["name"] for p in resp.json()["results"]]
        assert names == ["B Plan"]

    def test_public_portal_scoped_by_router_param(self, two_tenants):
        op_a, op_b = two_tenants
        PlanFactory(operator=op_a, name="A Plan")
        PlanFactory(operator=op_b, name="B Plan")
        router_a = RouterFactory(operator=op_a)

        resp = APIClient().get(f"/api/v1/plans/?router={router_a.id}")
        names = [p["name"] for p in resp.json()["results"]]
        assert names == ["A Plan"]

    def test_suspended_tenant_staff_blocked(self, two_tenants):
        op_a, _ = two_tenants
        op_a.status = Operator.Status.SUSPENDED
        op_a.save()
        resp = staff_client(op_a).get("/api/v1/payments/transactions/")
        assert resp.status_code == 403


class TestSignupAndApproval:
    SIGNUP = {
        "business_name": "Mtandao Wireless",
        "owner_name": "Jane Owner",
        "phone": "0722000111",
        "email": "jane@mtandao.co.ke",
        "password": "s3cure-pass!",
    }

    def test_signup_creates_pending_tenant(self, api_client):
        resp = api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        assert resp.status_code == 201, resp.content
        op = Operator.objects.get(slug="mtandao-wireless")
        assert op.status == Operator.Status.PENDING
        staff = op.users.get()
        assert staff.is_staff and staff.phone == "254722000111"

    def test_pending_tenant_staff_cannot_use_console(self, api_client):
        api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        op = Operator.objects.get(slug="mtandao-wireless")
        resp = staff_client(op).get("/api/v1/payments/transactions/")
        assert resp.status_code == 403

    def test_reserved_and_duplicate_slugs_rejected(self, api_client):
        bad = {**self.SIGNUP, "slug": "api"}
        assert api_client.post("/api/v1/tenants/signup/", bad, format="json").status_code == 400
        ok = api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        assert ok.status_code == 201
        dup = {**self.SIGNUP, "phone": "0722000112", "email": "x@y.co.ke"}
        assert api_client.post("/api/v1/tenants/signup/", dup, format="json").status_code == 400

    def test_platform_admin_approves(self, api_client):
        api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        op = Operator.objects.get(slug="mtandao-wireless")

        platform_admin = UserFactory(operator=None, is_staff=True, is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=platform_admin)
        resp = client.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200
        op.refresh_from_db()
        assert op.status == Operator.Status.ACTIVE
        assert op.approved_at is not None
        # now their staff can work
        assert staff_client(op).get("/api/v1/payments/transactions/").status_code == 200

    def test_tenant_staff_cannot_reach_platform_endpoints(self, two_tenants):
        op_a, _ = two_tenants
        resp = staff_client(op_a).get("/api/v1/platform/tenants/")
        assert resp.status_code == 403


class TestMe:
    def test_me_returns_tenant_context(self, two_tenants):
        op_a, _ = two_tenants
        resp = staff_client(op_a).get("/api/v1/me/")
        data = resp.json()
        assert data["operator"]["slug"] == "wisp-a"
        assert data["is_platform_admin"] is False

    def test_platform_admin_flag(self, db):
        admin = UserFactory(operator=None, is_staff=True, is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)
        data = client.get("/api/v1/me/").json()
        assert data["is_platform_admin"] is True
        assert data["operator"] is None
