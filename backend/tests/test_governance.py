"""Governance: the audit trail and impersonation.

Danamo holds other people's money. Platform staff entering an ISP's console must
be impossible to do silently — it requires a reason, expires, and is permanently
recorded. Setting the X-Act-As-Tenant header alone must NOT be enough.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import AuditLog, ImpersonationGrant

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db


def platform_client(operator=None, role=Role.PLATFORM_OWNER):
    user = UserFactory(operator=operator, is_staff=True, is_superuser=True, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    return c, user


class TestImpersonationIsRequired:
    """The hole this closes: previously ANY platform user could set
    X-Act-As-Tenant and silently read a tenant's data with no record."""

    def test_header_alone_does_not_grant_access(self):
        target = OperatorFactory(slug="victim")
        PppoeClientFactory(operator=target)
        c, _ = platform_client()
        c.credentials(HTTP_X_ACT_AS_TENANT="victim")
        resp = c.get("/api/v1/pppoe/clients/")
        # No grant -> tenant does not resolve -> RequireTenant refuses
        assert resp.status_code == 403, resp.content

    def test_access_works_after_starting_a_grant(self):
        target = OperatorFactory(slug="victim")
        PppoeClientFactory(operator=target)
        c, _ = platform_client()

        start = c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim", "reason": "Customer reported missing payment"},
            format="json",
        )
        assert start.status_code == 201, start.content

        c.credentials(HTTP_X_ACT_AS_TENANT="victim")
        resp = c.get("/api/v1/pppoe/clients/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_reason_is_mandatory(self):
        OperatorFactory(slug="victim")
        c, _ = platform_client()
        resp = c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim"},
            format="json",
        )
        assert resp.status_code == 400

    def test_expired_grant_stops_working(self):
        target = OperatorFactory(slug="victim")
        PppoeClientFactory(operator=target)
        c, user = platform_client()
        ImpersonationGrant.objects.create(
            actor=user,
            operator=target,
            reason="stale session",
            expires_at=timezone.now() - timedelta(minutes=1),  # already expired
        )
        c.credentials(HTTP_X_ACT_AS_TENANT="victim")
        assert c.get("/api/v1/pppoe/clients/").status_code == 403

    def test_ending_a_grant_revokes_access(self):
        target = OperatorFactory(slug="victim")
        PppoeClientFactory(operator=target)
        c, _ = platform_client()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim", "reason": "troubleshooting a router"},
            format="json",
        )
        c.credentials(HTTP_X_ACT_AS_TENANT="victim")
        assert c.get("/api/v1/pppoe/clients/").status_code == 200

        c.credentials()  # drop the act-as header to call the platform endpoint
        end = c.post("/api/v1/platform/impersonation/end/", {"tenant": "victim"}, format="json")
        assert end.json()["ended"] == 1

        c.credentials(HTTP_X_ACT_AS_TENANT="victim")
        assert c.get("/api/v1/pppoe/clients/").status_code == 403

    def test_grant_is_scoped_to_one_tenant(self):
        OperatorFactory(slug="isp-a")
        other = OperatorFactory(slug="isp-b")
        PppoeClientFactory(operator=other)
        c, _ = platform_client()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "isp-a", "reason": "checking their plans"},
            format="json",
        )
        # A grant for isp-a must not open isp-b
        c.credentials(HTTP_X_ACT_AS_TENANT="isp-b")
        assert c.get("/api/v1/pppoe/clients/").status_code == 403

    def test_own_isp_needs_no_grant(self):
        """Daniel runs his own WISP — reaching it is not impersonation."""
        own = OperatorFactory(slug="danamo-wisp")
        PppoeClientFactory(operator=own)
        c, _ = platform_client(operator=own)
        c.credentials(HTTP_X_ACT_AS_TENANT="danamo-wisp")
        assert c.get("/api/v1/pppoe/clients/").status_code == 200

    def test_cannot_impersonate_own_isp(self):
        own = OperatorFactory(slug="danamo-wisp")
        c, _ = platform_client(operator=own)
        resp = c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "danamo-wisp", "reason": "no need for this"},
            format="json",
        )
        assert resp.status_code == 400


class TestImpersonationIsRecorded:
    def test_start_and_end_are_audited(self):
        OperatorFactory(slug="victim")
        c, user = platform_client()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim", "reason": "billing dispute #123"},
            format="json",
        )
        c.post("/api/v1/platform/impersonation/end/", {"tenant": "victim"}, format="json")

        started = AuditLog.objects.get(action="impersonation_started")
        assert started.actor_id == user.id
        assert started.metadata["reason"] == "billing dispute #123"
        assert AuditLog.objects.filter(action="impersonation_ended").exists()

    def test_history_is_listable(self):
        OperatorFactory(slug="victim")
        c, _ = platform_client()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim", "reason": "deep troubleshooting"},
            format="json",
        )
        rows = c.get("/api/v1/platform/impersonation/").json()["results"]
        assert len(rows) == 1
        assert rows[0]["reason"] == "deep troubleshooting"
        assert rows[0]["is_live"] is True
        assert rows[0]["operator_slug"] == "victim"

    def test_live_filter(self):
        OperatorFactory(slug="victim")
        c, _ = platform_client()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "victim", "reason": "looking into a payment"},
            format="json",
        )
        assert len(c.get("/api/v1/platform/impersonation/?live=true").json()["results"]) == 1
        c.post("/api/v1/platform/impersonation/end/", {}, format="json")
        assert len(c.get("/api/v1/platform/impersonation/?live=true").json()["results"]) == 0


class TestAuditLogApi:
    def test_lists_and_filters(self):
        op = OperatorFactory(slug="acme")
        c, _ = platform_client()
        # Approving a tenant writes an audit row
        c.post(f"/api/v1/platform/tenants/{op.id}/approve/")

        rows = c.get("/api/v1/platform/audit/").json()["results"]
        assert any(r["action"] == "tenant_approved" for r in rows)

        filtered = c.get("/api/v1/platform/audit/?action=tenant_approved").json()
        assert filtered["count"] == 1
        assert filtered["results"][0]["operator_slug"] == "acme"

    def test_filter_by_tenant(self):
        """Approving writes two rows (tenant_activated from the shared activation
        service, plus tenant_approved) — what matters is that the filter returns
        ONLY tenant a's."""
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        c, _ = platform_client()
        c.post(f"/api/v1/platform/tenants/{a.id}/approve/")
        c.post(f"/api/v1/platform/tenants/{b.id}/approve/")

        rows = c.get("/api/v1/platform/audit/?tenant=a").json()["results"]
        assert rows, "tenant a should have audit rows"
        assert {r["operator_slug"] for r in rows} == {"a"}  # and nothing from b

    def test_action_names_endpoint(self):
        op = OperatorFactory()
        c, _ = platform_client()
        c.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert "tenant_approved" in c.get("/api/v1/platform/audit/actions/").json()

    def test_audit_is_read_only(self):
        c, _ = platform_client()
        assert c.post("/api/v1/platform/audit/", {}, format="json").status_code == 405

    def test_tenant_staff_cannot_read_the_audit_log(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        assert c.get("/api/v1/platform/audit/").status_code == 403
