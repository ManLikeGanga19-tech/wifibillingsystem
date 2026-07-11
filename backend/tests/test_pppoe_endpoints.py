"""PPPoE REST surface: full CRUD over plans / towers / access-points / clients /
invoices through the API, with tenant-isolation and validation edge cases. The
service-layer behaviour lives in test_pppoe.py; this file exercises the HTTP
endpoints an ISP console actually calls."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.models import AccessPoint, Client, ServicePlan, Tower

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    RouterFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def staff(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


class TestServicePlanCrud:
    def test_create_list_update_delete(self):
        op = OperatorFactory()
        c = staff(op)
        # create
        resp = c.post(
            "/api/v1/pppoe/plans/",
            {"name": "Home 8M", "price": "1500.00", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "home-8m"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        plan_id = resp.json()["id"]
        # list
        assert c.get("/api/v1/pppoe/plans/").json()["count"] == 1
        # update (price change)
        resp = c.patch(f"/api/v1/pppoe/plans/{plan_id}/", {"price": "1800.00"}, format="json")
        assert resp.status_code == 200
        assert ServicePlan.objects.get(pk=plan_id).price == Decimal("1800.00")
        # delete
        assert c.delete(f"/api/v1/pppoe/plans/{plan_id}/").status_code == 204
        assert not ServicePlan.objects.filter(pk=plan_id).exists()

    def test_plans_are_tenant_isolated(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        ServicePlanFactory(operator=op_a)
        ServicePlanFactory(operator=op_b)
        assert staff(op_a).get("/api/v1/pppoe/plans/").json()["count"] == 1

    def test_cannot_read_another_tenants_plan_detail(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        plan_b = ServicePlanFactory(operator=op_b)
        assert staff(op_a).get(f"/api/v1/pppoe/plans/{plan_b.id}/").status_code == 404


class TestTowerCrud:
    def test_create_and_annotated_ap_count(self):
        op = OperatorFactory()
        c = staff(op)
        resp = c.post("/api/v1/pppoe/towers/", {"name": "Nyeri Hill"}, format="json")
        assert resp.status_code == 201, resp.content
        tower_id = resp.json()["id"]
        # add two APs, then confirm the annotation
        for name in ("Sector A", "Sector B"):
            AccessPoint.objects.create(
                operator=op, tower_id=tower_id, name=name, capacity=10
            )
        row = next(
            t for t in c.get("/api/v1/pppoe/towers/").json()["results"] if t["id"] == tower_id
        )
        assert row["access_point_count"] == 2

    def test_tower_isolation(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        Tower.objects.create(operator=op_a, name="A-tower")
        Tower.objects.create(operator=op_b, name="B-tower")
        assert staff(op_a).get("/api/v1/pppoe/towers/").json()["count"] == 1


class TestAccessPointCrud:
    def test_create_ap_on_own_tower(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T1")
        resp = staff(op).post(
            "/api/v1/pppoe/access-points/",
            {"tower": tower.id, "name": "Sector N", "mode": "ptmp",
             "band": "5GHz", "capacity": 30},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["capacity"] == 30
        # utilization is a list-view annotation; on the fresh create response it is
        # None (no client_count annotated). The list endpoint reports 0 (verified
        # in test_utilization_null / over_subscribed).
        row = next(
            r for r in staff(op).get("/api/v1/pppoe/access-points/").json()["results"]
            if r["id"] == resp.json()["id"]
        )
        assert row["utilization"] == 0  # capacity set, no clients yet

    def test_cannot_attach_ap_to_another_tenants_tower(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        tower_b = Tower.objects.create(operator=op_b, name="B-tower")
        resp = staff(op_a).post(
            "/api/v1/pppoe/access-points/",
            {"tower": tower_b.id, "name": "X", "capacity": 5},
            format="json",
        )
        assert resp.status_code == 400  # foreign tower FK rejected

    def test_utilization_null_when_capacity_unset(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="Legacy", capacity=0)
        PppoeClientFactory.create_batch(3, operator=op, access_point=ap, status="active")
        row = next(
            r for r in staff(op).get("/api/v1/pppoe/access-points/").json()["results"]
            if r["id"] == ap.id
        )
        assert row["client_count"] == 3
        assert row["utilization"] is None

    def test_over_subscribed_reports_above_100(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="Sector", capacity=4)
        PppoeClientFactory.create_batch(5, operator=op, access_point=ap, status="active")
        row = next(
            r for r in staff(op).get("/api/v1/pppoe/access-points/").json()["results"]
            if r["id"] == ap.id
        )
        assert row["utilization"] == 125

    def test_suspended_clients_count_toward_utilization(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="S", capacity=10)
        PppoeClientFactory.create_batch(2, operator=op, access_point=ap, status="active")
        PppoeClientFactory.create_batch(2, operator=op, access_point=ap, status="suspended")
        PppoeClientFactory(operator=op, access_point=ap, status="disabled")  # excluded
        row = next(
            r for r in staff(op).get("/api/v1/pppoe/access-points/").json()["results"]
            if r["id"] == ap.id
        )
        assert row["client_count"] == 4  # active + suspended, not disabled
        assert row["utilization"] == 40


class TestClientEndpoints:
    def test_status_filter(self):
        op = OperatorFactory()
        PppoeClientFactory.create_batch(2, operator=op, status="active")
        PppoeClientFactory(operator=op, status="suspended")
        c = staff(op)
        assert c.get("/api/v1/pppoe/clients/?status=active").json()["count"] == 2
        assert c.get("/api/v1/pppoe/clients/?status=suspended").json()["count"] == 1

    def test_account_number_is_read_only_on_create(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op)
        router = RouterFactory(operator=op)
        resp = staff(op).post(
            "/api/v1/pppoe/clients/",
            {"full_name": "Y", "plan": plan.id, "router": router.id,
             "account_number": "HACKED123"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["account_number"] != "HACKED123"  # server-generated

    def test_provision_action_activates(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="pending_install")
        resp = staff(op).post(f"/api/v1/pppoe/clients/{client.id}/provision/")
        assert resp.status_code == 200, resp.content
        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE

    def test_suspend_then_restore_actions(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        c = staff(op)
        assert c.post(f"/api/v1/pppoe/clients/{client.id}/suspend/").status_code == 200
        client.refresh_from_db()
        assert client.status == Client.Status.SUSPENDED
        assert c.post(f"/api/v1/pppoe/clients/{client.id}/restore/").status_code == 200
        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE

    def test_cannot_act_on_another_tenants_client(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        client_b = PppoeClientFactory(operator=op_b)
        assert staff(op_a).post(
            f"/api/v1/pppoe/clients/{client_b.id}/suspend/"
        ).status_code == 404


class TestInvoiceEndpoints:
    def test_invoices_read_only_no_create(self):
        op = OperatorFactory()
        # POST is not allowed on a read-only viewset
        resp = staff(op).post("/api/v1/pppoe/invoices/", {}, format="json")
        assert resp.status_code == 405

    def test_invoice_list_and_status_filter(self):
        from django.utils import timezone

        from apps.pppoe.services import issue_invoice

        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))
        issue_invoice(client, timezone.localdate())
        c = staff(op)
        assert c.get("/api/v1/pppoe/invoices/").json()["count"] == 1
        assert c.get("/api/v1/pppoe/invoices/?status=unpaid").json()["count"] == 1
        assert c.get("/api/v1/pppoe/invoices/?status=paid").json()["count"] == 0

    def test_invoices_tenant_isolated(self):
        from django.utils import timezone

        from apps.pppoe.services import issue_invoice

        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        for op in (op_a, op_b):
            issue_invoice(
                PppoeClientFactory(operator=op, plan__price=Decimal("2000")),
                timezone.localdate(),
            )
        assert staff(op_a).get("/api/v1/pppoe/invoices/").json()["count"] == 1


class TestSupportRoleReadOnly:
    def test_support_cannot_create_plan(self):
        op = OperatorFactory()
        c = staff(op, role=Role.TENANT_SUPPORT)
        resp = c.post(
            "/api/v1/pppoe/plans/",
            {"name": "P", "price": "1500", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "p"},
            format="json",
        )
        assert resp.status_code == 403
