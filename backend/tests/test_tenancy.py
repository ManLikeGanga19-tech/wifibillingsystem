"""Tenant isolation: the security property the whole SaaS stands on."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
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

    def test_pending_tenant_staff_CAN_use_the_console(self, api_client):
        """Changed deliberately in Phase B ("explore now, money later"): a pending
        ISP gets their console immediately and can do real work. What they cannot do
        is take a shilling — that is the separate money gate (see test_money_gate).
        Locking them out until approval was a waiting room, and it killed the
        momentum of someone who has just signed up."""
        api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        op = Operator.objects.get(slug="mtandao-wireless")
        assert op.status == Operator.Status.PENDING

        resp = staff_client(op).get("/api/v1/payments/transactions/")
        assert resp.status_code == 200
        # ...but the money gate is shut.
        assert op.can_transact is False

    def test_suspended_tenant_staff_are_locked_out(self, api_client):
        """Pending is a waiting room with the lights on. Suspended is a locked door."""
        api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        op = Operator.objects.get(slug="mtandao-wireless")
        op.status = Operator.Status.SUSPENDED
        op.save()
        assert staff_client(op).get("/api/v1/payments/transactions/").status_code == 403

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

        platform_admin = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
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


class TestIdentitySeparation:
    """Login accounts (User) and customers (Subscriber) are separate identities.
    A phone can be a customer at several ISPs AND own an ISP account."""

    SIGNUP = {
        "business_name": "Mtandao Wireless",
        "owner_name": "Jane Owner",
        "phone": "0722000111",
        "email": "jane@mtandao.co.ke",
        "password": "s3cure-pass!",
    }

    def test_existing_customer_can_register_an_isp(self, api_client, two_tenants):
        """The reported bug: a phone that bought WiFi as a customer must still be
        able to sign up as an ISP owner."""
        from apps.accounts.models import Subscriber

        op_a, _ = two_tenants
        Subscriber.objects.create(operator=op_a, phone="254722000111", name="Jane the customer")

        resp = api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        assert resp.status_code == 201, resp.content
        # Both identities coexist
        assert Subscriber.objects.filter(operator=op_a, phone="254722000111").exists()
        assert User.objects.filter(phone="254722000111", is_staff=True).exists()

    def test_same_phone_is_a_distinct_customer_at_each_isp(self, two_tenants):
        """Previously the second ISP's get_or_create returned the FIRST ISP's row,
        silently mis-attributing the customer."""
        from apps.accounts.models import Subscriber

        op_a, op_b = two_tenants
        sub_a, created_a = Subscriber.get_or_create_for(op_a, "0733111222")
        sub_b, created_b = Subscriber.get_or_create_for(op_b, "0733111222")

        assert created_a and created_b
        assert sub_a.pk != sub_b.pk
        assert sub_a.operator == op_a and sub_b.operator == op_b

    def test_subscriber_is_idempotent_within_one_isp(self, two_tenants):
        from apps.accounts.models import Subscriber

        op_a, _ = two_tenants
        first, _ = Subscriber.get_or_create_for(op_a, "0733111222")
        again, created = Subscriber.get_or_create_for(op_a, "254733111222")  # same, normalized
        assert not created
        assert first.pk == again.pk

    def test_duplicate_login_phone_still_rejected(self, api_client):
        """Two ISP owners cannot share a login phone — that would break auth."""
        first = api_client.post("/api/v1/tenants/signup/", self.SIGNUP, format="json")
        assert first.status_code == 201
        dup = {**self.SIGNUP, "business_name": "Other ISP", "email": "x@y.co.ke"}
        assert api_client.post("/api/v1/tenants/signup/", dup, format="json").status_code == 400

    def test_customers_are_not_login_accounts(self, two_tenants):
        from apps.accounts.models import Subscriber

        op_a, _ = two_tenants
        Subscriber.objects.create(operator=op_a, phone="254799888777")
        assert not User.objects.filter(phone="254799888777").exists()


class TestMe:
    def test_me_returns_tenant_context(self, two_tenants):
        op_a, _ = two_tenants
        data = staff_client(op_a).get("/api/v1/me/").json()
        assert data["operator"]["slug"] == "wisp-a"
        assert data["acting_operator"]["slug"] == "wisp-a"
        assert data["is_platform_staff"] is False
        assert data["role"] == Role.TENANT_OWNER

    def test_platform_staff_flag(self, db):
        admin = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        data = client.get("/api/v1/me/").json()
        assert data["is_platform_staff"] is True
        assert data["can_manage_money"] is True
        assert data["operator"] is None
        assert data["acting_operator"] is None  # must pick an ISP to see ISP data

    def test_platform_owner_can_also_own_an_isp(self, two_tenants):
        """Daniel's shape: one login, two hats."""
        op_a, _ = two_tenants
        daniel = UserFactory(
            operator=op_a, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        client = APIClient()
        client.force_authenticate(user=daniel)
        data = client.get("/api/v1/me/").json()
        assert data["is_platform_staff"] is True
        assert data["operator"]["slug"] == "wisp-a"
        assert data["acting_operator"]["slug"] == "wisp-a"
