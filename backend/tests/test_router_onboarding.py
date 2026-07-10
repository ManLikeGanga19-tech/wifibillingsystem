"""Router self-onboarding + re-sync resilience."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Router, Session
from apps.provisioning.sync import sync_router_sessions

from .factories import OperatorFactory, RouterFactory, SessionFactory, UserFactory

pytestmark = pytest.mark.django_db


def staff_client(operator):
    client = APIClient()
    client.force_authenticate(user=UserFactory(operator=operator, is_staff=True))
    return client


class TestEnrollment:
    def test_new_router_starts_pending(self):
        router = RouterFactory(management_host="")
        assert router.status == Router.Status.PENDING
        assert not router.is_enrolled
        assert router.enrollment_token

    def test_setup_script_contains_token_and_ids(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op, management_host="")
        resp = staff_client(op).get(f"/api/v1/routers/{router.id}/setup_script/")
        assert resp.status_code == 200
        script = resp.json()["script"]
        assert router.enrollment_token in script
        assert f"router={router.id}" in script
        assert "/tool fetch" in script  # phones home

    def test_phone_home_enrolls_router(self):
        router = RouterFactory(management_host="", provisioning_backend=Router.Backend.DUMMY)
        resp = APIClient().post(
            "/api/v1/routers/enroll/",
            data=json.dumps(
                {"token": router.enrollment_token, "api_password": "secret123", "version": "7.16.2"}
            ),
            content_type="application/json",
            HTTP_X_FORWARDED_FOR="41.90.1.2",
        )
        assert resp.status_code == 200
        router.refresh_from_db()
        assert router.is_enrolled
        assert router.status == Router.Status.ONLINE
        assert router.management_host == "41.90.1.2"
        assert router.password == "secret123"
        assert router.routeros_version == "7.16.2"

    def test_bad_token_rejected(self):
        resp = APIClient().post(
            "/api/v1/routers/enroll/",
            data=json.dumps({"token": "nope", "api_password": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_setup_script_is_tenant_scoped(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        router_b = RouterFactory(operator=op_b, management_host="")
        resp = staff_client(op_a).get(f"/api/v1/routers/{router_b.id}/setup_script/")
        assert resp.status_code == 404


class TestReSync:
    def test_reprovisions_missing_active_sessions(self):
        router = RouterFactory(provisioning_backend=Router.Backend.DUMMY)
        # Active in DB, but the (rebooted) router reports NO live users
        session = SessionFactory(router=router, operator=router.operator)
        DummyAdapter.calls = []

        report = sync_router_sessions(router)

        assert report["reprovisioned"] == 1
        assert ("activate", session.hotspot_username) in DummyAdapter.calls

    def test_expires_overdue_sessions(self):
        router = RouterFactory(provisioning_backend=Router.Backend.DUMMY)
        session = SessionFactory(
            router=router, operator=router.operator, expires_at=timezone.now() - timedelta(hours=1)
        )
        report = sync_router_sessions(router)

        session.refresh_from_db()
        assert session.status == Session.Status.EXPIRED
        assert report["expired"] == 1

    def test_sync_updates_timestamp(self):
        router = RouterFactory(provisioning_backend=Router.Backend.DUMMY)
        assert router.last_sync_at is None
        sync_router_sessions(router)
        router.refresh_from_db()
        assert router.last_sync_at is not None

    def test_resync_endpoint_requires_enrollment(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op, management_host="")  # not enrolled
        resp = staff_client(op).post(f"/api/v1/routers/{router.id}/resync/")
        assert resp.status_code == 409
