"""Phase 2 of the fibre plant: the API. Capacity (used/free) is computed, blast-radius walks the
graph, deletes are soft, spans stay same-tenant, and fibre.write gates it all.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.fibre.models import FibrePoint, FibreSpan

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, UserFactory


def api_as(role, operator):
    user = UserFactory(role=role, operator=operator, is_staff=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def pt(op, type_, label, **kw):
    return FibrePoint.objects.create(operator=op, type=type_, label=label, **kw)


@pytest.fixture
def op(db):
    return OperatorFactory()


@pytest.mark.django_db
class TestPlantCrudAndCapacity:
    def test_create_point_and_capacity_is_computed(self, op):
        api = api_as(Role.TENANT_TECHNICIAN, op)
        resp = api.post(reverse("fibre-point-list"), {
            "type": FibrePoint.Type.ODP, "label": "ODP-7", "port_capacity": 16}, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["used"] == 0 and resp.data["free"] == 16

        # Hang three fibre customers off it → used 3, free 13.
        odp = FibrePoint.objects.get(id=resp.data["id"])
        router = RouterFactory(operator=op)
        for _ in range(3):
            PppoeClientFactory(operator=op, router=router, delivery_method="fibre", fibre_point=odp)
        got = api.get(reverse("fibre-point-detail", args=[odp.id])).data
        assert got["used"] == 3 and got["free"] == 13

    def test_structural_point_has_no_capacity(self, op):
        api = api_as(Role.TENANT_OWNER, op)
        p = pt(op, FibrePoint.Type.POLE, "Pole-3")
        got = api.get(reverse("fibre-point-detail", args=[p.id])).data
        assert got["used"] == 0 and got["free"] is None   # capacity n/a on a pole

    def test_delete_is_soft_and_restorable(self, op):
        api = api_as(Role.TENANT_OWNER, op)
        p = pt(op, FibrePoint.Type.ODP, "ODP-1")
        assert api.delete(reverse("fibre-point-detail", args=[p.id])).status_code == 204
        p.refresh_from_db()
        assert p.is_active is False
        # gone from the default list, present with include_inactive
        assert all(r["id"] != p.id for r in api.get(reverse("fibre-point-list")).data["results"])
        listed = api.get(reverse("fibre-point-list") + "?include_inactive=1").data["results"]
        assert any(r["id"] == p.id for r in listed)
        # restore brings it back
        assert api.post(reverse("fibre-point-restore", args=[p.id])).status_code == 200
        p.refresh_from_db()
        assert p.is_active is True


@pytest.mark.django_db
class TestSpans:
    def test_create_span_and_reject_self_loop(self, op):
        api = api_as(Role.TENANT_TECHNICIAN, op)
        a, b = pt(op, FibrePoint.Type.OLT_POP, "OLT"), pt(op, FibrePoint.Type.ODP, "ODP")
        ok = api.post(reverse("fibre-span-list"), {
            "from_point": a.id, "to_point": b.id, "cable_type": "adss", "fibre_count": 24},
            format="json")
        assert ok.status_code == 201
        loop = api.post(reverse("fibre-span-list"), {
            "from_point": a.id, "to_point": a.id, "cable_type": "adss"}, format="json")
        assert loop.status_code == 400

    def test_span_cannot_reach_another_tenants_point(self, op):
        other = OperatorFactory(slug="other-isp")
        mine = pt(op, FibrePoint.Type.OLT_POP, "OLT")
        theirs = pt(other, FibrePoint.Type.ODP, "ODP")
        api = api_as(Role.TENANT_OWNER, op)
        resp = api.post(reverse("fibre-span-list"), {
            "from_point": mine.id, "to_point": theirs.id, "cable_type": "adss"}, format="json")
        assert resp.status_code == 400   # the other tenant's point isn't in the field's queryset


@pytest.mark.django_db
class TestBlastRadius:
    def test_affected_walks_downstream(self, op):
        router = RouterFactory(operator=op)
        olt = pt(op, FibrePoint.Type.OLT_POP, "OLT")
        spl = pt(op, FibrePoint.Type.SPLITTER, "SPL", port_capacity=16, splitter_ratio="1:16")
        odp1 = pt(op, FibrePoint.Type.ODP, "ODP-1", port_capacity=8)
        odp2 = pt(op, FibrePoint.Type.ODP, "ODP-2", port_capacity=8)
        FibreSpan.objects.create(operator=op, from_point=olt, to_point=spl)
        FibreSpan.objects.create(operator=op, from_point=spl, to_point=odp1)
        FibreSpan.objects.create(operator=op, from_point=spl, to_point=odp2)
        c1 = PppoeClientFactory(operator=op, router=router, fibre_point=odp1)
        c2 = PppoeClientFactory(operator=op, router=router, fibre_point=odp2)
        c3 = PppoeClientFactory(operator=op, router=router, fibre_point=odp1)

        api = api_as(Role.TENANT_TECHNICIAN, op)

        # A fault at the splitter darkens both ODPs → all three customers.
        at_spl = api.get(reverse("fibre-point-affected", args=[spl.id])).data
        assert at_spl["count"] == 3
        assert {r["id"] for r in at_spl["clients"]} == {c1.id, c2.id, c3.id}

        # A fault at ODP-1 → only its two customers.
        at_odp1 = api.get(reverse("fibre-point-affected", args=[odp1.id])).data
        assert {r["id"] for r in at_odp1["clients"]} == {c1.id, c3.id}

        # Splitter "used" = its two downstream cables.
        spl_state = api.get(reverse("fibre-point-detail", args=[spl.id])).data
        assert spl_state["used"] == 2 and spl_state["free"] == 14


@pytest.mark.django_db
class TestFibreApiRbac:
    def test_care_cannot_touch_the_plant_but_technician_can(self, op):
        care = api_as(Role.TENANT_CARE, op)
        assert care.get(reverse("fibre-point-list")).status_code == 403
        assert care.post(reverse("fibre-point-list"), {}).status_code == 403

        tech = api_as(Role.TENANT_TECHNICIAN, op)
        assert tech.get(reverse("fibre-point-list")).status_code == 200
