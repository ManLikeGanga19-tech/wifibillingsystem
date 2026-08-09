"""The read-only demo tenant: fully seeded to LOOK at, but the API refuses every write so
anyone can explore WIFI.OS without changing data. Enforced once, in RequireTenant, so it
covers every endpoint — these prove reads pass and writes are politely refused."""

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import Operator
from apps.pppoe.models import Client

from .factories import OperatorFactory, UserFactory

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
