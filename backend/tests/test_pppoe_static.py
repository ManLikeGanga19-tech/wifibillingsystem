"""Static-IP subscribers: a second connection type that reuses the ENTIRE PPPoE billing
engine (invoices, suspend sweep, churn) and differs only in the router verbs — a /queue/simple
+ a firewall address-list instead of a /ppp/secret. These pin the lifecycle and the guards."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.models import Client
from apps.pppoe.services import (
    cancel_client,
    create_client,
    provision_client,
    restore_client,
    suspend_client,
)
from apps.provisioning.adapters.dummy import DummyAdapter

from .factories import (
    OperatorFactory,
    RouterFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

IP = "10.20.0.5"


def _static(op, **kw):
    plan = kw.pop("plan", None) or ServicePlanFactory(operator=op)
    router = kw.pop("router", None) or RouterFactory(operator=op)
    return create_client(
        operator=op, plan=plan, router=router,
        connection_type=Client.Connection.STATIC, static_ip=IP,
        full_name="Static Sam", billing_day=1, **kw,
    )


class TestStaticLifecycle:
    def test_created_static_client_has_no_login(self):
        op = OperatorFactory()
        c = _static(op)
        assert c.is_static
        assert c.pppoe_username is None
        assert c.pppoe_password == ""

    def test_provision_creates_a_queue_and_enables_it(self):
        op = OperatorFactory()
        c = _static(op)
        DummyAdapter.calls = []
        provision_client(c)
        assert ("static_queue", IP) in DummyAdapter.calls
        assert ("static_enable", IP) in DummyAdapter.calls
        # a static line never touches PPPoE secrets
        assert not any(call[0].startswith("pppoe_") for call in DummyAdapter.calls)
        c.refresh_from_db()
        assert c.status == Client.Status.ACTIVE

    def test_suspend_restore_cancel_use_the_static_verbs(self):
        op = OperatorFactory()
        c = _static(op)
        provision_client(c)

        DummyAdapter.calls = []
        suspend_client(c)
        assert ("static_suspend", IP) in DummyAdapter.calls
        c.refresh_from_db()
        assert c.status == Client.Status.SUSPENDED

        DummyAdapter.calls = []
        restore_client(c)
        assert ("static_enable", IP) in DummyAdapter.calls

        suspend_client(c)  # overdue again
        DummyAdapter.calls = []
        cancel_client(c)
        assert ("static_remove", IP) in DummyAdapter.calls
        c.refresh_from_db()
        assert c.status == Client.Status.CANCELLED


class TestStaticApi:
    def _staff(self, op):
        c = APIClient()
        c.force_authenticate(user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER))
        return c

    def _payload(self, op, **over):
        plan = ServicePlanFactory(operator=op)
        router = RouterFactory(operator=op)
        base = {
            "full_name": "Static Sam", "connection_type": "static", "static_ip": "10.20.0.9",
            "plan": plan.id, "router": router.id, "billing_day": 1,
        }
        base.update(over)
        return base

    def test_create_static_client_through_the_api(self):
        op = OperatorFactory()
        resp = self._staff(op).post("/api/v1/pppoe/clients/", self._payload(op), format="json")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["connection_type"] == "static"
        assert body["static_ip"] == "10.20.0.9"
        assert body["pppoe_username"] in (None, "")

    def test_static_client_requires_an_ip(self):
        op = OperatorFactory()
        resp = self._staff(op).post(
            "/api/v1/pppoe/clients/", self._payload(op, static_ip=""), format="json"
        )
        assert resp.status_code == 400
        assert "static_ip" in str(resp.json()).lower()

    def test_connection_type_cannot_be_changed(self):
        op = OperatorFactory()
        c = _static(op)
        resp = self._staff(op).patch(
            f"/api/v1/pppoe/clients/{c.id}/", {"connection_type": "pppoe"}, format="json"
        )
        assert resp.status_code == 400


class TestStaticInheritsBilling:
    def test_overdue_static_client_is_suspended_by_the_sweep(self):
        from apps.pppoe.models import Invoice
        from apps.pppoe.tasks import suspend_overdue_clients

        op = OperatorFactory()
        c = _static(op)
        provision_client(c)  # -> ACTIVE
        # an overdue invoice + negative balance, exactly like a PPPoE client
        from datetime import timedelta

        from django.utils import timezone
        today = timezone.localdate()
        Invoice.objects.create(
            operator=op, client=c, number=f"INV-{c.account_number}",
            period_start=today.replace(day=1), period_end=today,
            amount=Decimal("2000"), due_date=today - timedelta(days=1),
            status=Invoice.Status.UNPAID,
        )
        Client.objects.filter(pk=c.pk).update(balance=Decimal("-2000"))

        DummyAdapter.calls = []
        suspend_overdue_clients()
        c.refresh_from_db()
        assert c.status == Client.Status.SUSPENDED
        assert ("static_suspend", IP) in DummyAdapter.calls  # the static verb, not PPPoE
