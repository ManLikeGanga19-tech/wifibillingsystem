"""The read-only demo tenant: fully seeded to LOOK at, but the API refuses every write so
anyone can explore WIFI.OS without changing data. Enforced once, in RequireTenant, so it
covers every endpoint — these prove reads pass and writes are politely refused."""

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import Operator
from apps.pppoe.models import Client

from .factories import OperatorFactory, ServicePlanFactory, UserFactory

pytestmark = pytest.mark.django_db


def _client(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


class TestDemoIsReadOnly:
    def test_reads_are_allowed(self):
        op = OperatorFactory(slug="demo", is_demo=True)
        resp = _client(op).get("/api/v1/pppoe/plans/")
        assert resp.status_code == 200

    def test_writes_are_refused_with_a_friendly_notice(self):
        op = OperatorFactory(slug="demo", is_demo=True)
        resp = _client(op).post(
            "/api/v1/pppoe/plans/",
            {"name": "X", "price": "1000.00", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "x"},
            format="json",
        )
        assert resp.status_code == 403
        assert "read-only demo" in str(resp.data).lower()

    def test_money_and_delete_are_refused_too(self):
        op = OperatorFactory(slug="demo", is_demo=True)
        c = _client(op)
        assert c.delete("/api/v1/pppoe/plans/1/").status_code == 403
        # a PATCH is a write as well
        assert c.patch("/api/v1/pppoe/plans/1/", {"name": "y"}, format="json").status_code == 403

    def test_a_normal_tenant_can_still_write(self):
        op = OperatorFactory(slug="real", is_demo=False)
        resp = _client(op).post(
            "/api/v1/pppoe/plans/",
            {"name": "Real Plan", "price": "1500.00", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "real"},
            format="json",
        )
        assert resp.status_code == 201


class TestDemoHostPinsTheDemoTenant:
    """Auth cookies are scoped to .wifios.co.ke, so a real user's session rides along to
    demo.wifios.co.ke. The demo host must show the DEMO tenant regardless of who's logged
    in — otherwise you'd see your own ISP on the demo subdomain."""

    def test_other_users_session_still_sees_the_demo_on_the_demo_host(self):
        demo = OperatorFactory(slug="demo", is_demo=True)
        ServicePlanFactory(operator=demo, name="Demo Bronze")
        mine = OperatorFactory(slug="homelink", is_demo=False)
        ServicePlanFactory(operator=mine, name="My Secret Plan")

        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=mine, is_staff=True, role=Role.TENANT_OWNER)
        )
        # Same authenticated user, but the request arrives on the demo host.
        resp = c.get("/api/v1/pppoe/plans/", HTTP_HOST="demo.wifios.co.ke")
        names = [p["name"] for p in resp.json()["results"]]
        assert "Demo Bronze" in names
        assert "My Secret Plan" not in names

    def test_demo_host_is_read_only_even_for_a_real_user(self):
        OperatorFactory(slug="demo", is_demo=True)
        mine = OperatorFactory(slug="homelink", is_demo=False)
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=mine, is_staff=True, role=Role.TENANT_OWNER)
        )
        resp = c.post(
            "/api/v1/pppoe/plans/",
            {"name": "X", "price": "1000.00", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "x"},
            format="json", HTTP_HOST="demo.wifios.co.ke",
        )
        assert resp.status_code == 403


class TestDemoLogin:
    def test_demo_login_signs_you_in_on_the_demo_host(self):
        demo = OperatorFactory(slug="demo", is_demo=True)
        UserFactory(operator=demo, is_staff=True, role=Role.TENANT_OWNER)
        c = APIClient()
        resp = c.post("/api/v1/auth/demo/", HTTP_HOST="demo.wifios.co.ke")
        assert resp.status_code == 200
        # the session cookie is set, so a follow-up /me works with no credentials
        assert "wifios_access" in resp.cookies

    def test_demo_login_is_refused_on_a_normal_host(self):
        OperatorFactory(slug="homelink", is_demo=False)
        c = APIClient()
        resp = c.post("/api/v1/auth/demo/", HTTP_HOST="homelink.wifios.co.ke")
        assert resp.status_code == 404


class TestSeedDemo:
    def test_seed_is_idempotent_and_populates(self):
        call_command("seed_demo")
        op = Operator.objects.get(slug="demo")
        assert op.is_demo is True
        first = Client.objects.filter(operator=op).count()
        assert first > 0

        # second run rebuilds the same snapshot without error or duplication
        call_command("seed_demo")
        assert Client.objects.filter(operator=op).count() == first
