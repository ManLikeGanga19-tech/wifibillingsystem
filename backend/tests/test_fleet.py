"""Phase 1 of fleet tracking: a technician reports their own position, a dispatcher sees the live
fleet (latest per tech), and the privacy guarantees hold — you can only report yourself, only
dispatchers can look, it's tenant-scoped, and the trail is pruned.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import Role
from apps.fleet.models import TechLocationPing
from apps.fleet.tasks import prune_location_pings

from .factories import OperatorFactory, UserFactory


def api_as(role, operator):
    user = UserFactory(role=role, operator=operator, is_staff=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


@pytest.fixture
def op(db):
    return OperatorFactory()


@pytest.mark.django_db
class TestFleetCapabilities:
    def test_share_and_view_are_split_across_roles(self, op):
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op)
        assert tech.has_capability(rbac.FLEET_SHARE)
        assert not tech.has_capability(rbac.FLEET_VIEW)          # a tech sees only itself
        care = UserFactory(role=Role.TENANT_CARE, operator=op)
        assert care.has_capability(rbac.FLEET_VIEW)             # dispatcher
        assert not care.has_capability(rbac.FLEET_SHARE)         # care doesn't report
        for role in (Role.TENANT_ADMIN, Role.TENANT_OWNER):
            u = UserFactory(role=role, operator=op)
            assert u.has_capability(rbac.FLEET_VIEW) and u.has_capability(rbac.FLEET_SHARE)


@pytest.mark.django_db
class TestPing:
    def test_technician_reports_and_it_is_stored_for_them(self, op):
        api, tech = api_as(Role.TENANT_TECHNICIAN, op)
        resp = api.post(reverse("fleet-ping"),
                        {"lat": "-1.29", "lng": "36.82", "accuracy": 25}, format="json")
        assert resp.status_code == 201
        ping = TechLocationPing.objects.get(operator=op)
        assert ping.technician_id == tech.id and str(ping.lat) == "-1.290000"

    def test_you_can_only_report_yourself(self, op):
        api, tech = api_as(Role.TENANT_TECHNICIAN, op)
        other = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op)
        # A spoofed technician in the payload is ignored — the ping is always the caller's.
        api.post(reverse("fleet-ping"),
                 {"lat": "-1.1", "lng": "36.1", "technician": other.id}, format="json")
        ping = TechLocationPing.objects.get(operator=op)
        assert ping.technician_id == tech.id

    def test_care_cannot_report_but_can_view(self, op):
        care, _ = api_as(Role.TENANT_CARE, op)
        assert care.post(reverse("fleet-ping"), {"lat": "-1.2", "lng": "36.8"}).status_code == 403
        assert care.get(reverse("fleet")).status_code == 200


@pytest.mark.django_db
class TestFleetView:
    def test_dispatcher_sees_latest_per_technician(self, op):
        t1 = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, name="Otieno")
        now = timezone.now()
        TechLocationPing.objects.create(operator=op, technician=t1, lat="-1.1", lng="36.1",
                                        recorded_at=now - timedelta(minutes=5))
        TechLocationPing.objects.create(operator=op, technician=t1, lat="-1.2", lng="36.2",
                                        recorded_at=now)   # newest
        care, _ = api_as(Role.TENANT_CARE, op)
        body = care.get(reverse("fleet")).data
        assert len(body["members"]) == 1                    # one row per tech
        assert str(body["members"][0]["lat"]) == "-1.200000"   # the newest fix
        assert body["members"][0]["is_live"] is True

    def test_stale_ping_is_not_live(self, op):
        t1 = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op)
        TechLocationPing.objects.create(operator=op, technician=t1, lat="-1.1", lng="36.1",
                                        recorded_at=timezone.now() - timedelta(hours=2))
        body = api_as(Role.TENANT_OWNER, op)[0].get(reverse("fleet")).data
        assert body["members"][0]["is_live"] is False

    def test_technician_cannot_see_the_fleet(self, op):
        assert api_as(Role.TENANT_TECHNICIAN, op)[0].get(reverse("fleet")).status_code == 403

    def test_fleet_is_tenant_scoped(self, op):
        other = OperatorFactory(slug="other-isp")
        their_tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=other)
        TechLocationPing.objects.create(operator=other, technician=their_tech, lat="1", lng="1")
        body = api_as(Role.TENANT_OWNER, op)[0].get(reverse("fleet")).data
        assert body["members"] == []                        # never another ISP's fleet


@pytest.mark.django_db
class TestPrune:
    def test_prune_deletes_pings_past_the_window(self, op, settings):
        settings.FLEET_RETENTION_HOURS = 24
        t1 = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op)
        now = timezone.now()
        TechLocationPing.objects.create(operator=op, technician=t1, lat="1", lng="1",
                                        recorded_at=now - timedelta(hours=48))   # old
        TechLocationPing.objects.create(operator=op, technician=t1, lat="2", lng="2",
                                        recorded_at=now - timedelta(hours=1))    # recent
        result = prune_location_pings()
        assert result["deleted"] == 1
        assert TechLocationPing.objects.count() == 1        # only the recent one survives
