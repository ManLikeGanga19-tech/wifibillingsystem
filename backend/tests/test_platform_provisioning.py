"""Platform Control can hand-onboard an ISP (skipping the marketing signup wizard) and can
stand up the demo tenant in one click. Both are owner-gated and both return credentials to
pass on by hand."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Operator

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db


def _platform(owner=True):
    role = Role.PLATFORM_OWNER if owner else Role.PLATFORM_SUPPORT
    c = APIClient()
    c.force_authenticate(user=UserFactory(is_staff=True, role=role))
    return c


class TestProvisionTenant:
    def _payload(self, **over):
        base = {"name": "Sunrise Networks", "slug": "sunrise", "owner_phone": "0712345678",
                "owner_name": "Jane Owner"}
        base.update(over)
        return base

    def test_owner_provisions_an_isp_and_gets_working_credentials(self):
        resp = _platform().post("/api/v1/platform/tenants/provision/", self._payload(),
                                format="json")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "sunrise"
        assert body["owner_phone"] == "254712345678"  # normalised
        assert body["temp_password"]
        assert body["console_url"] == "https://sunrise.wifios.co.ke"

        op = Operator.objects.get(slug="sunrise")
        assert op.status == Operator.Status.PENDING  # same gate as self-signup
        # the owner login actually works with the returned temporary password
        login = APIClient().post(
            "/api/v1/auth/login/",
            {"phone": "254712345678", "password": body["temp_password"]},
            format="json",
        )
        assert login.status_code == 200

    def test_reserved_slug_is_refused(self):
        resp = _platform().post("/api/v1/platform/tenants/provision/",
                                self._payload(slug="admin"), format="json")
        assert resp.status_code == 400

    def test_duplicate_slug_is_refused(self):
        OperatorFactory(slug="taken")
        resp = _platform().post("/api/v1/platform/tenants/provision/",
                                self._payload(slug="taken"), format="json")
        assert resp.status_code == 409

    def test_bad_phone_is_refused(self):
        resp = _platform().post("/api/v1/platform/tenants/provision/",
                                self._payload(owner_phone="nope"), format="json")
        assert resp.status_code == 400

    def test_support_cannot_provision(self):
        resp = _platform(owner=False).post("/api/v1/platform/tenants/provision/",
                                           self._payload(), format="json")
        assert resp.status_code == 403


class TestCreateDemo:
    def test_owner_creates_the_demo_tenant(self):
        resp = _platform().post("/api/v1/platform/tenants/create-demo/", {}, format="json")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "demo"
        assert body["owner_phone"] and body["temp_password"]

        op = Operator.objects.get(slug="demo")
        assert op.is_demo is True
        assert User.objects.filter(operator=op, is_staff=True).exists()

    def test_support_cannot_create_demo(self):
        resp = _platform(owner=False).post("/api/v1/platform/tenants/create-demo/", {},
                                           format="json")
        assert resp.status_code == 403
