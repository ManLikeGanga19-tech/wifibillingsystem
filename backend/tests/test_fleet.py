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
class TestNearestAndDispatch:
    def _place(self, op, name, lat, lng, minutes_ago=0):
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, name=name, is_staff=True)
        TechLocationPing.objects.create(
            operator=op, technician=tech, lat=str(lat), lng=str(lng),
            recorded_at=timezone.now() - timedelta(minutes=minutes_ago))
        return tech

    def test_nearest_ranks_live_techs_by_distance(self, op):
        near = self._place(op, "Near", -1.30, 36.81)     # ~close to target below
        far = self._place(op, "Far", -1.10, 36.95)       # further
        self._place(op, "Stale", -1.301, 36.811, minutes_ago=120)   # closest but dark → excluded
        care, _ = api_as(Role.TENANT_CARE, op)
        body = care.get(reverse("fleet-nearest") + "?lat=-1.30&lng=36.81").data
        ids = [t["technician_id"] for t in body["technicians"]]
        assert ids == [near.id, far.id]                  # stale one dropped, nearest first
        assert body["technicians"][0]["distance_km"] < body["technicians"][1]["distance_km"]

    def test_nearest_needs_valid_coords_and_fleet_view(self, op):
        care, _ = api_as(Role.TENANT_CARE, op)
        assert care.get(reverse("fleet-nearest")).status_code == 400          # no coords
        tech, _ = api_as(Role.TENANT_TECHNICIAN, op)   # not a dispatcher → 403
        assert tech.get(reverse("fleet-nearest") + "?lat=-1&lng=36").status_code == 403

    def test_dispatch_assigns_the_nearest_technician(self, op):
        from apps.ops.models import Ticket
        near = self._place(op, "Near", -1.30, 36.81)
        self._place(op, "Far", -1.10, 36.95)
        ticket = Ticket.objects.create(operator=op, subject="Fibre down at ODP-7")
        care, _ = api_as(Role.TENANT_CARE, op)
        resp = care.post(reverse("ticket-dispatch", args=[ticket.id]),
                         {"lat": "-1.30", "lng": "36.81"}, format="json")
        assert resp.status_code == 200
        assert resp.data["technician_id"] == near.id
        ticket.refresh_from_db()
        assert ticket.assigned_to_id == near.id

    def test_dispatch_needs_tickets_assign(self, op):
        from apps.ops.models import Ticket
        self._place(op, "Near", -1.30, 36.81)
        ticket = Ticket.objects.create(operator=op, subject="x")
        tech, _ = api_as(Role.TENANT_TECHNICIAN, op)   # can work, cannot assign/dispatch
        assert tech.post(reverse("ticket-dispatch", args=[ticket.id]),
                         {"lat": "-1.3", "lng": "36.8"}, format="json").status_code == 403

    def test_dispatch_with_no_live_tech_is_a_clean_409(self, op):
        from apps.ops.models import Ticket
        self._place(op, "Dark", -1.30, 36.81, minutes_ago=120)   # only a stale tech
        ticket = Ticket.objects.create(operator=op, subject="x")
        care, _ = api_as(Role.TENANT_CARE, op)
        resp = care.post(reverse("ticket-dispatch", args=[ticket.id]),
                         {"lat": "-1.3", "lng": "36.8"}, format="json")
        assert resp.status_code == 409


@pytest.mark.django_db
class TestTechnicianJob:
    def test_dispatch_stamps_the_fault_location_and_notifies_the_tech(self, op):
        from apps.notifications.models import Message
        from apps.ops.models import Ticket
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, name="Otieno", is_staff=True)
        TechLocationPing.objects.create(operator=op, technician=tech, lat="-1.30", lng="36.81")
        ticket = Ticket.objects.create(operator=op, subject="Fibre down")
        care, _ = api_as(Role.TENANT_CARE, op)

        resp = care.post(reverse("ticket-dispatch", args=[ticket.id]),
                         {"lat": "-1.30", "lng": "36.81"}, format="json")
        assert resp.status_code == 200
        ticket.refresh_from_db()
        assert str(ticket.gps_lat) == "-1.300000"          # the tech can navigate to it
        # the technician got an SMS with the job
        msg = Message.objects.filter(operator=op, to_phone=tech.phone).first()
        assert msg is not None and "Fibre down" in msg.body and "maps" in msg.body.lower()

    def test_manual_assign_notifies_and_bypasses_the_customer_sms_toggle(self, op):
        from apps.notifications.models import Message
        from apps.ops.models import Ticket
        op.notify_customers_sms = False       # customer SMS off — staff alerts still go
        op.save(update_fields=["notify_customers_sms"])
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, is_staff=True)
        ticket = Ticket.objects.create(operator=op, subject="No internet")
        care, _ = api_as(Role.TENANT_CARE, op)

        resp = care.patch(reverse("ticket-detail", args=[ticket.id]), {"assigned_to": tech.id})
        assert resp.status_code == 200
        assert Message.objects.filter(operator=op, to_phone=tech.phone).exists()

    def test_ticket_badge_is_scoped_to_the_technician(self, op):
        from apps.ops.models import Ticket
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, is_staff=True)
        Ticket.objects.create(operator=op, subject="mine", assigned_to=tech)
        Ticket.objects.create(operator=op, subject="someone else's")   # open, not theirs

        tech_api = APIClient()
        tech_api.force_authenticate(user=tech)
        assert tech_api.get(reverse("nav-counts")).data["tickets"] == 1     # only their assigned
        # a dispatcher's badge counts the whole ISP's open tickets
        care, _ = api_as(Role.TENANT_CARE, op)
        assert care.get(reverse("nav-counts")).data["tickets"] == 2


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
