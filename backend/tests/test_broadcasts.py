"""Platform broadcasts — Danamo speaking to every ISP console. Pins owner-gating on
composing, per-user dismissal, and the live/expired/pinned rules for what a tenant sees."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import BroadcastDismissal, PlatformBroadcast

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _owner():
    return _client(UserFactory(is_staff=True, role=Role.PLATFORM_OWNER))


def _support():
    return _client(UserFactory(is_staff=True, role=Role.PLATFORM_SUPPORT))


def _isp_user():
    op = OperatorFactory(slug=f"bc-{uuid.uuid4().hex[:8]}")
    return _client(UserFactory(operator=op, role=Role.TENANT_OWNER))


def _make(**kw):
    kw.setdefault("title", "Notice")
    kw.setdefault("body", "Something to know")
    return PlatformBroadcast.objects.create(**kw)


class TestCompose:
    def test_owner_creates_support_cannot(self):
        r = _owner().post("/api/v1/platform/broadcasts/",
                          {"title": "Maintenance", "body": "Sun 2am", "level": "warning"},
                          format="json")
        assert r.status_code == 201, r.content
        assert PlatformBroadcast.objects.filter(title="Maintenance").exists()

        r = _support().post("/api/v1/platform/broadcasts/",
                            {"title": "Nope", "body": "x"}, format="json")
        assert r.status_code == 403

    def test_staff_can_list(self):
        _make()
        assert _support().get("/api/v1/platform/broadcasts/").status_code == 200

    def test_retire_hides_from_tenants(self):
        b = _make()
        assert len(_isp_user().get("/api/v1/broadcasts/active/").json()) == 1
        _owner().patch(f"/api/v1/platform/broadcasts/{b.id}/", {"is_active": False}, format="json")
        assert len(_isp_user().get("/api/v1/broadcasts/active/").json()) == 0


class TestTenantView:
    def test_active_excludes_inactive_future_and_expired(self):
        now = timezone.now()
        _make(title="live")
        _make(title="off", is_active=False)
        _make(title="future", starts_at=now + timedelta(days=1))
        _make(title="expired", ends_at=now - timedelta(hours=1))

        titles = {b["title"] for b in _isp_user().get("/api/v1/broadcasts/active/").json()}
        assert titles == {"live"}

    def test_dismiss_is_per_user(self):
        b = _make()
        me = _isp_user()
        other = _isp_user()

        assert me.post(f"/api/v1/broadcasts/{b.id}/dismiss/").status_code == 200
        assert len(me.get("/api/v1/broadcasts/active/").json()) == 0       # gone for me
        assert len(other.get("/api/v1/broadcasts/active/").json()) == 1     # still there for them
        assert BroadcastDismissal.objects.filter(broadcast=b).count() == 1

    def test_pinned_cannot_be_dismissed(self):
        b = _make(dismissable=False)
        r = _isp_user().post(f"/api/v1/broadcasts/{b.id}/dismiss/")
        assert r.status_code == 400
        assert not BroadcastDismissal.objects.filter(broadcast=b).exists()

    def test_requires_auth(self):
        assert APIClient().get("/api/v1/broadcasts/active/").status_code in (401, 403)
