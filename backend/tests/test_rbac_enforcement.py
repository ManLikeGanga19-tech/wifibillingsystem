"""Phase 2 of tenant RBAC: the gates actually bite on real endpoints, and the row/field scoping
holds. We assert the boundary by STATUS: 403 means the capability gate refused; a non-403
(200/400/201) means the gate let the request through to the view. Owner/Admin are exercised by the
existing 1000+ tests (they hold every capability); here we pin the delegated roles.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.ops.models import Ticket

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, UserFactory


def rows(resp):
    data = resp.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


def client_for(role, operator):
    user = UserFactory(role=role, operator=operator, is_staff=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


@pytest.fixture
def op(db):
    return OperatorFactory()


@pytest.mark.django_db
class TestEndpointAccessByRole:
    def test_clients_readable_by_every_role(self, op):
        for role in Role.tenant_roles():
            api, _ = client_for(role, op)
            assert api.get(reverse("pppoe-client-list")).status_code == 200, role

    def test_network_is_hidden_from_care_but_open_to_technician(self, op):
        for name in ("pppoe-tower-list", "router-list"):
            assert client_for(Role.TENANT_CARE, op)[0].get(reverse(name)).status_code == 403
            assert client_for(Role.TENANT_TECHNICIAN, op)[0].get(reverse(name)).status_code == 200

    def test_money_screens_are_finance_only(self, op):
        # The revenue dashboard is included: hiding its nav isn't enough — the endpoint refuses too.
        for name in ("transaction-list", "ledger-list", "wallet-summary", "dashboard-stats"):
            url = reverse(name)
            assert client_for(Role.TENANT_CARE, op)[0].get(url).status_code == 403, name
            assert client_for(Role.TENANT_TECHNICIAN, op)[0].get(url).status_code == 403, name
            assert client_for(Role.TENANT_ADMIN, op)[0].get(url).status_code == 200, name

    def test_leads_are_read_only_for_the_technician(self, op):
        tech = client_for(Role.TENANT_TECHNICIAN, op)[0]
        assert tech.get(reverse("lead-list")).status_code == 200        # may read (map layer)
        assert tech.post(reverse("lead-list"), {}).status_code == 403   # may not write the CRM
        care = client_for(Role.TENANT_CARE, op)[0]
        # gate passes for Care (validation may still 400)
        assert care.post(reverse("lead-list"), {}).status_code != 403

    def test_technician_cannot_create_a_client_but_care_can(self, op):
        assert client_for(Role.TENANT_TECHNICIAN, op)[0].post(
            reverse("pppoe-client-list"), {}).status_code == 403
        assert client_for(Role.TENANT_CARE, op)[0].post(
            reverse("pppoe-client-list"), {}).status_code != 403


@pytest.mark.django_db
class TestTicketRowScoping:
    def test_technician_sees_only_their_assigned_tickets(self, op):
        tech_api, tech_user = client_for(Role.TENANT_TECHNICIAN, op)
        mine = Ticket.objects.create(operator=op, subject="mine", assigned_to=tech_user)
        Ticket.objects.create(operator=op, subject="someone else's")

        got = rows(tech_api.get(reverse("ticket-list")))
        assert [t["id"] for t in got] == [mine.id]

        # Care (can assign) sees the whole queue.
        care_api, _ = client_for(Role.TENANT_CARE, op)
        assert len(rows(care_api.get(reverse("ticket-list")))) == 2

    def test_technician_may_work_a_ticket_but_not_reassign_it(self, op):
        tech_api, tech_user = client_for(Role.TENANT_TECHNICIAN, op)
        other = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, is_staff=True)
        t = Ticket.objects.create(operator=op, subject="x", assigned_to=tech_user)

        resp = tech_api.patch(
            reverse("ticket-detail", args=[t.id]),
            {"status": "in_progress", "assigned_to": other.id},
        )
        assert resp.status_code == 200
        t.refresh_from_db()
        assert t.status == "in_progress"          # working it is allowed
        assert t.assigned_to_id == tech_user.id   # re-routing is silently dropped (tickets.assign)


@pytest.mark.django_db
class TestClientFieldScoping:
    def test_technician_edit_is_limited_to_status_and_location(self, op):
        router = RouterFactory(operator=op)
        client = PppoeClientFactory(
            operator=op, router=router, full_name="Original", status="active")
        tech_api, _ = client_for(Role.TENANT_TECHNICIAN, op)

        resp = tech_api.patch(
            reverse("pppoe-client-detail", args=[client.id]),
            {"full_name": "Renamed by tech", "gps_lat": "-1.290000", "gps_lng": "36.820000"},
        )
        assert resp.status_code == 200
        client.refresh_from_db()
        assert client.full_name == "Original"        # the name edit was dropped
        assert str(client.gps_lat) == "-1.290000"    # location was applied
