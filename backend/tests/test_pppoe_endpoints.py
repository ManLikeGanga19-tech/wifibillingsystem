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
        """Read-only means read-only, even for platform staff inside a tenant."""
        op = OperatorFactory()
        c = staff(op, role=Role.PLATFORM_SUPPORT)
        resp = c.post(
            "/api/v1/pppoe/plans/",
            {"name": "P", "price": "1500", "download_kbps": 8192,
             "upload_kbps": 4096, "mikrotik_profile": "p"},
            format="json",
        )
        assert resp.status_code == 403


class TestSectorCapacity:
    """Adding a client to a full sector warns (409) but never blocks: force=true proceeds and
    is audited, so an over-subscription is recorded as the ISP's own call."""

    def _full_sector(self, op, capacity=2, tower_name="Nyeri Hill", sector="Sector A"):
        tower = Tower.objects.create(operator=op, name=tower_name)
        ap = AccessPoint.objects.create(operator=op, tower=tower, name=sector, capacity=capacity)
        PppoeClientFactory.create_batch(capacity, operator=op, access_point=ap, status="active")
        return ap

    def _payload(self, op, ap=None, **extra):
        d = {
            "full_name": "New Client",
            "plan": ServicePlanFactory(operator=op).id,
            "router": RouterFactory(operator=op).id,
        }
        if ap is not None:
            d["access_point"] = ap.id
        d.update(extra)
        return d

    def test_adding_to_a_full_sector_warns_with_409(self):
        op = OperatorFactory()
        ap = self._full_sector(op, capacity=2)
        resp = staff(op).post("/api/v1/pppoe/clients/", self._payload(op, ap), format="json")
        assert resp.status_code == 409, resp.content
        body = resp.json()
        assert body["code"] == "sector_at_capacity"
        assert body["count"] == 2 and body["capacity"] == 2
        assert body["sector"] == "Sector A" and body["tower"] == "Nyeri Hill"

    def test_the_warning_creates_no_client(self):
        op = OperatorFactory()
        ap = self._full_sector(op, capacity=2)
        before = Client.objects.filter(operator=op).count()
        staff(op).post("/api/v1/pppoe/clients/", self._payload(op, ap), format="json")
        assert Client.objects.filter(operator=op).count() == before

    def test_force_adds_over_capacity_and_audits(self):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        ap = self._full_sector(op, capacity=2)
        resp = staff(op).post(
            "/api/v1/pppoe/clients/", self._payload(op, ap, force=True), format="json"
        )
        assert resp.status_code == 201, resp.content
        assert AuditLog.objects.filter(operator=op, action="pppoe_over_capacity_add").exists()

    def test_room_available_creates_without_warning(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="S", capacity=5)
        PppoeClientFactory.create_batch(2, operator=op, access_point=ap, status="active")
        resp = staff(op).post("/api/v1/pppoe/clients/", self._payload(op, ap), format="json")
        assert resp.status_code == 201, resp.content

    def test_unset_capacity_never_warns(self):
        op = OperatorFactory()
        tower = Tower.objects.create(operator=op, name="T")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="S", capacity=0)
        PppoeClientFactory.create_batch(9, operator=op, access_point=ap, status="active")
        resp = staff(op).post("/api/v1/pppoe/clients/", self._payload(op, ap), format="json")
        assert resp.status_code == 201, resp.content

    def test_no_access_point_never_warns(self):
        op = OperatorFactory()
        resp = staff(op).post("/api/v1/pppoe/clients/", self._payload(op), format="json")
        assert resp.status_code == 201, resp.content

    def test_moving_a_client_onto_a_full_sector_warns_then_forces(self):
        op = OperatorFactory()
        full = self._full_sector(op, capacity=2)
        client = PppoeClientFactory(operator=op, status="active")  # not on any sector
        c = staff(op)
        blocked = c.patch(
            f"/api/v1/pppoe/clients/{client.id}/", {"access_point": full.id}, format="json"
        )
        assert blocked.status_code == 409, blocked.content
        forced = c.patch(
            f"/api/v1/pppoe/clients/{client.id}/",
            {"access_point": full.id, "force": True}, format="json",
        )
        assert forced.status_code == 200, forced.content


class TestClientCredentials:
    """PPPoE dial credentials: readable on the dashboard, settable at create, resettable
    (hybrid — typed or generated), and never changed by a plain edit."""

    def _create(self, op, **extra):
        plan = ServicePlanFactory(operator=op)
        router = RouterFactory(operator=op)
        payload = {"full_name": "Jane", "plan": plan.id, "router": router.id, **extra}
        return staff(op).post("/api/v1/pppoe/clients/", payload, format="json")

    def test_password_is_readable_on_the_dashboard(self):
        # The gap this feature closes: the create response (and detail) carries the password
        # so the ISP can hand it to an installer.
        resp = self._create(OperatorFactory())
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["pppoe_username"] and body["pppoe_password"]

    def test_blank_credentials_autogenerate(self):
        resp = self._create(OperatorFactory(), pppoe_username="", pppoe_password="")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert len(body["pppoe_username"]) >= 3
        assert len(body["pppoe_password"]) >= 6

    def test_isp_can_set_their_own_credentials(self):
        resp = self._create(
            OperatorFactory(), pppoe_username="janedoe", pppoe_password="hunter2x"
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["pppoe_username"] == "janedoe"
        assert body["pppoe_password"] == "hunter2x"

    def test_short_password_is_rejected_on_create(self):
        assert self._create(OperatorFactory(), pppoe_password="x").status_code == 400

    def test_a_plain_edit_cannot_change_the_password(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, pppoe_password="original1")
        staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/",
            {"pppoe_password": "sneaky99", "full_name": "New Name"}, format="json",
        )
        client.refresh_from_db()
        assert client.pppoe_password == "original1"  # creds untouched by a plain edit
        assert client.full_name == "New Name"  # the real edit still applied

    def test_reset_generates_a_new_password(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active", pppoe_password="original1")
        resp = staff(op).post(f"/api/v1/pppoe/clients/{client.id}/reset_password/")
        assert resp.status_code == 200, resp.content
        new = resp.json()["pppoe_password"]
        assert new and new != "original1"
        client.refresh_from_db()
        assert client.pppoe_password == new

    def test_reset_with_a_typed_password(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        resp = staff(op).post(
            f"/api/v1/pppoe/clients/{client.id}/reset_password/",
            {"password": "chosen123"}, format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["pppoe_password"] == "chosen123"
        client.refresh_from_db()
        assert client.pppoe_password == "chosen123"

    def test_reset_rejects_a_short_password(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        resp = staff(op).post(
            f"/api/v1/pppoe/clients/{client.id}/reset_password/",
            {"password": "x"}, format="json",
        )
        assert resp.status_code == 400

    def test_reset_keeps_a_suspended_client_suspended(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="suspended")
        assert staff(op).post(
            f"/api/v1/pppoe/clients/{client.id}/reset_password/"
        ).status_code == 200
        client.refresh_from_db()
        assert client.status == Client.Status.SUSPENDED  # reset didn't silently un-suspend

    def test_delete_removes_the_client(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        assert staff(op).delete(f"/api/v1/pppoe/clients/{client.id}/").status_code == 204
        assert not Client.objects.filter(pk=client.id).exists()

    def test_cannot_reset_another_tenants_client(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        client_b = PppoeClientFactory(operator=op_b)
        assert staff(op_a).post(
            f"/api/v1/pppoe/clients/{client_b.id}/reset_password/"
        ).status_code == 404


class TestClientImportExport:
    """Adopt an ISP's pre-existing router PPPoE users, and export clients as CSV."""

    def _secrets(self, secrets):
        from apps.provisioning.adapters.dummy import DummyAdapter
        DummyAdapter.pppoe_secrets = secrets

    def test_export_returns_csv_of_clients(self):
        op = OperatorFactory()
        c1 = PppoeClientFactory(operator=op)
        resp = staff(op).get("/api/v1/pppoe/clients/export/")
        assert resp.status_code == 200
        assert "text/csv" in resp["Content-Type"]
        body = b"".join(resp.streaming_content).decode()
        assert c1.account_number in body and c1.pppoe_username in body

    def test_import_preview_flags_managed_and_suggests_a_plan(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        plan = ServicePlanFactory(operator=op, mikrotik_profile="home-8m")
        PppoeClientFactory(operator=op, pppoe_username="olduser")
        self._secrets([
            {"username": "olduser", "password": "x", "profile": "home-8m"},
            {"username": "newuser", "password": "y", "profile": "home-8m", "comment": "Jane"},
        ])
        resp = staff(op).post(
            "/api/v1/pppoe/clients/import-preview/", {"router": router.id}, format="json"
        )
        assert resp.status_code == 200, resp.content
        rows = {r["username"]: r for r in resp.json()}
        assert rows["olduser"]["already_managed"] is True
        assert rows["newuser"]["already_managed"] is False
        assert rows["newuser"]["suggested_plan"] == plan.id

    def test_import_adopts_new_users_and_skips_managed(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        plan = ServicePlanFactory(operator=op)
        PppoeClientFactory(operator=op, pppoe_username="olduser")
        self._secrets([
            {"username": "olduser", "password": "x", "profile": "p"},
            {"username": "newuser", "password": "secretpw", "profile": "p", "comment": "Jane"},
        ])
        resp = staff(op).post("/api/v1/pppoe/clients/import/", {
            "router": router.id,
            "items": [
                {"username": "olduser", "plan": plan.id},
                {"username": "newuser", "full_name": "Jane Doe", "plan": plan.id},
            ],
        }, format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert [i["username"] for i in body["imported"]] == ["newuser"]
        assert body["skipped"][0]["username"] == "olduser"
        new = Client.objects.get(pppoe_username="newuser")
        assert new.pppoe_password == "secretpw"  # adopted the router's exact password
        assert new.full_name == "Jane Doe"
        assert new.status == Client.Status.ACTIVE

    def test_import_is_idempotent(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        plan = ServicePlanFactory(operator=op)
        self._secrets([{"username": "u1", "password": "p", "profile": "p"}])
        payload = {"router": router.id, "items": [{"username": "u1", "plan": plan.id}]}
        first = staff(op).post("/api/v1/pppoe/clients/import/", payload, format="json").json()
        assert len(first["imported"]) == 1
        second = staff(op).post("/api/v1/pppoe/clients/import/", payload, format="json").json()
        assert len(second["imported"]) == 0
        assert second["skipped"][0]["reason"] == "already managed"

    def test_import_skips_a_row_with_no_valid_plan(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        self._secrets([{"username": "u1", "password": "p", "profile": "p"}])
        resp = staff(op).post("/api/v1/pppoe/clients/import/", {
            "router": router.id, "items": [{"username": "u1", "plan": 999999}],
        }, format="json")
        assert resp.status_code == 200
        assert resp.json()["skipped"][0]["reason"] == "no plan chosen"
        assert not Client.objects.filter(pppoe_username="u1").exists()


class TestClientEdit:
    """Editing a client must change the ROUTER too — a DB-only save would leave the MikroTik
    enforcing the old plan (or holding the secret on the old router) with nobody able to tell
    which is true."""

    def _calls(self):
        from apps.provisioning.adapters.dummy import DummyAdapter
        return DummyAdapter.calls

    def _reset(self):
        from apps.provisioning.adapters.dummy import DummyAdapter
        DummyAdapter.calls = []

    def test_editing_contact_details_saves_without_touching_the_router(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        self._reset()
        resp = staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/",
            {"full_name": "New Name", "phone": "0712000111", "physical_address": "Nyeri",
             "billing_day": 15},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        client.refresh_from_db()
        assert client.full_name == "New Name"
        assert client.billing_day == 15
        assert self._calls() == []  # bookkeeping only — no router work

    def test_changing_the_plan_repushes_the_profile_and_bounces_the_session(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="active")
        new_plan = ServicePlanFactory(operator=op, mikrotik_profile="home-gold")
        self._reset()
        resp = staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/", {"plan": new_plan.id}, format="json"
        )
        assert resp.status_code == 200, resp.content
        client.refresh_from_db()
        assert client.plan_id == new_plan.id
        kinds = [c[0] for c in self._calls()]
        assert "ensure_profile" in kinds  # new plan's profile exists on the router
        assert "pppoe_create" in kinds    # secret re-pushed onto it
        assert "pppoe_kick" in kinds      # live session bounced so the new speed applies now

    def test_moving_to_another_router_creates_then_removes(self):
        op = OperatorFactory()
        old_router = RouterFactory(operator=op)
        new_router = RouterFactory(operator=op)
        client = PppoeClientFactory(operator=op, router=old_router, status="active")
        self._reset()
        resp = staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/", {"router": new_router.id}, format="json"
        )
        assert resp.status_code == 200, resp.content
        client.refresh_from_db()
        assert client.router_id == new_router.id
        kinds = [c[0] for c in self._calls()]
        # Create on the NEW router BEFORE removing from the old — never leave a customer
        # with no secret anywhere.
        assert kinds.index("pppoe_create") < kinds.index("pppoe_remove")

    def test_a_suspended_client_stays_suspended_after_a_plan_change(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="suspended")
        new_plan = ServicePlanFactory(operator=op)
        self._reset()
        staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/", {"plan": new_plan.id}, format="json"
        )
        client.refresh_from_db()
        assert client.status == Client.Status.SUSPENDED
        # Re-walled: an edit must never quietly reconnect someone who hasn't paid.
        assert "pppoe_suspend" in [c[0] for c in self._calls()]

    def test_an_edit_cannot_change_the_account_number(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op)
        original = client.account_number
        staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/",
            {"account_number": "HACKED1", "full_name": "Moved House"}, format="json",
        )
        client.refresh_from_db()
        assert client.account_number == original  # permanent payment reference
        assert client.full_name == "Moved House"  # the real edit still applied

    def test_a_pending_client_edit_does_no_router_work(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, status="pending_install")
        new_plan = ServicePlanFactory(operator=op)
        self._reset()
        staff(op).patch(
            f"/api/v1/pppoe/clients/{client.id}/", {"plan": new_plan.id}, format="json"
        )
        assert self._calls() == []  # nothing on a router yet; provision writes it later

    def test_cannot_edit_another_tenants_client(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        client_b = PppoeClientFactory(operator=op_b)
        resp = staff(op_a).patch(
            f"/api/v1/pppoe/clients/{client_b.id}/", {"full_name": "X"}, format="json"
        )
        assert resp.status_code == 404


class TestClientSearchAndBillingDate:
    def test_search_matches_account_name_phone_and_username(self):
        op = OperatorFactory()
        target = PppoeClientFactory(
            operator=op, full_name="Jane Ngure", phone="0722123456",
            pppoe_username="jane-x1", account_number="HOME99001",
        )
        PppoeClientFactory(operator=op, full_name="Other Person", phone="0700000000")
        c = staff(op)
        for term in ("HOME99001", "ngure", "0722123456", "jane-x1"):
            rows = c.get(f"/api/v1/pppoe/clients/?search={term}").json()["results"]
            assert [r["id"] for r in rows] == [target.id], f"search {term!r} failed"

    def test_search_never_reaches_another_tenant(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        PppoeClientFactory(operator=op_b, full_name="Jane Ngure")
        rows = staff(op_a).get("/api/v1/pppoe/clients/?search=ngure").json()["results"]
        assert rows == []

    def test_search_combines_with_the_status_filter(self):
        op = OperatorFactory()
        PppoeClientFactory(operator=op, full_name="Jane A", status="active")
        PppoeClientFactory(operator=op, full_name="Jane B", status="suspended")
        rows = staff(op).get(
            "/api/v1/pppoe/clients/?search=jane&status=active"
        ).json()["results"]
        assert [r["full_name"] for r in rows] == ["Jane A"]

    def test_next_billing_date_is_projected_before_the_first_invoice(self):
        """A freshly-onboarded client showed a blank due date until the monthly run, which
        reads as 'billing isn't set up'. Project it from their billing day instead."""
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, billing_day=15, next_due_date=None)
        row = staff(op).get(f"/api/v1/pppoe/clients/{client.id}/").json()
        assert row["next_billing_date"]  # never blank
        assert row["next_due_is_projected"] is True
        assert row["next_billing_date"].endswith("-15")  # their billing day

    def test_a_real_invoice_due_date_wins_over_the_projection(self):
        import datetime

        op = OperatorFactory()
        due = datetime.date(2026, 9, 3)
        client = PppoeClientFactory(operator=op, billing_day=15, next_due_date=due)
        row = staff(op).get(f"/api/v1/pppoe/clients/{client.id}/").json()
        assert row["next_billing_date"] == "2026-09-03"
        assert row["next_due_is_projected"] is False


class TestPublicAccountLookupIsNotEnumerable:
    """Audit F2. This endpoint is anonymous and returns a real person's name and debt, so
    knowing the account number must not be enough on its own."""

    def _client_on(self, op, **kw):
        router = RouterFactory(operator=op)
        return PppoeClientFactory(operator=op, router=router, **kw), router

    def _lookup(self, router, **params):
        from urllib.parse import urlencode
        qs = urlencode({"router": router.id, **params})
        return APIClient().get(f"/api/v1/pppoe/account-lookup/?{qs}")

    def test_the_right_account_and_phone_digits_succeed(self):
        op = OperatorFactory()
        client, router = self._client_on(op, phone="0722123456", full_name="Jane Ngure")
        resp = self._lookup(router, account=client.account_number, phone="3456")
        assert resp.status_code == 200, resp.content
        assert resp.json()["full_name"] == "Jane Ngure"

    def test_the_account_number_alone_is_not_enough(self):
        op = OperatorFactory()
        client, router = self._client_on(op, phone="0722123456")
        assert self._lookup(router, account=client.account_number).status_code == 404

    def test_wrong_phone_digits_are_refused(self):
        op = OperatorFactory()
        client, router = self._client_on(op, phone="0722123456")
        assert self._lookup(
            router, account=client.account_number, phone="0000"
        ).status_code == 404

    def test_a_wrong_account_and_a_wrong_phone_are_indistinguishable(self):
        """Otherwise the endpoint is an oracle: 'this account exists, keep guessing'."""
        op = OperatorFactory()
        client, router = self._client_on(op, phone="0722123456")
        real_account_wrong_phone = self._lookup(
            router, account=client.account_number, phone="0000"
        )
        no_such_account = self._lookup(router, account="NOSUCH1", phone="3456")
        assert real_account_wrong_phone.status_code == no_such_account.status_code == 404
        assert real_account_wrong_phone.json() == no_such_account.json()

    def test_a_client_with_no_phone_on_file_cannot_be_looked_up(self):
        op = OperatorFactory()
        client, router = self._client_on(op, phone="")
        assert self._lookup(
            router, account=client.account_number, phone="1234"
        ).status_code == 404

    def test_full_phone_number_also_works(self):
        """Customers type what they know; we compare the last four either way."""
        op = OperatorFactory()
        client, router = self._client_on(op, phone="0722123456")
        assert self._lookup(
            router, account=client.account_number, phone="0722123456"
        ).status_code == 200


class TestCredentialExportIsGated:
    """Audit F3. PPPoE passwords are plaintext of necessity, so a bulk export must be
    deliberate, restricted, and recorded — without ever blocking an ISP from leaving."""

    def _export(self, op, **params):
        from urllib.parse import urlencode
        qs = f"?{urlencode(params)}" if params else ""
        return staff(op).get(f"/api/v1/pppoe/clients/export/{qs}")

    def test_the_plain_export_carries_no_passwords(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, pppoe_password="topsecret1")
        body = b"".join(self._export(op).streaming_content).decode()
        assert client.account_number in body  # the data is all still there
        assert "topsecret1" not in body
        assert "pppoe_password" not in body

    def test_the_owner_can_still_take_their_credentials_with_them(self):
        """Data portability is a promise: an ISP leaving must be able to take everything,
        or they would have to re-provision every customer's router by hand."""
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, pppoe_password="topsecret1")
        body = b"".join(
            self._export(op, include_credentials="true").streaming_content
        ).decode()
        assert "topsecret1" in body
        assert client.pppoe_username in body

    def test_a_credential_export_is_audited(self):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        PppoeClientFactory(operator=op)
        self._export(op, include_credentials="true")
        entry = AuditLog.objects.filter(action="pppoe_clients_exported").first()
        assert entry is not None
        assert entry.metadata.get("include_credentials") is True

    def test_the_export_is_tenant_scoped(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        theirs = PppoeClientFactory(operator=op_b, pppoe_password="theirsecret")
        body = b"".join(
            self._export(op_a, include_credentials="true").streaming_content
        ).decode()
        assert theirs.account_number not in body
        assert "theirsecret" not in body
