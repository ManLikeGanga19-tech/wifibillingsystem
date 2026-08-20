"""Shortest-path routing over the fibre plant (Dijkstra).

The plant is a weighted graph; these tests pin that the route is the CHEAPEST one by total
metres (not the fewest hops), that a field user's GPS snaps onto the nearest point, that a
customer resolves to their ODP, and that it's gated on map.view + tenant-scoped.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.fibre.models import FibrePoint, FibreSpan

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db
URL = reverse("fibre-route")


def api_as(role, operator):
    api = APIClient()
    api.force_authenticate(UserFactory(role=role, operator=operator, is_staff=True))
    return api


def pt(op, label, lat=None, lng=None, type_=FibrePoint.Type.SPLITTER):
    return FibrePoint.objects.create(
        operator=op, type=type_, label=label,
        gps_lat=Decimal(str(lat)) if lat is not None else None,
        gps_lng=Decimal(str(lng)) if lng is not None else None,
    )


def span(op, a, b, length_m):
    return FibreSpan.objects.create(
        operator=op, from_point=a, to_point=b, cable_type="adss", length_m=length_m)


class TestShortestRoute:
    def test_picks_cheapest_by_metres_not_fewest_hops(self, db):
        """A→B→D (100+100=200m) must beat the single long span A→D (500m)."""
        op = OperatorFactory()
        a = pt(op, "A", -1.30, 36.80, type_=FibrePoint.Type.CABINET)
        b = pt(op, "B", -1.31, 36.80)
        d = pt(op, "D", -1.32, 36.80, type_=FibrePoint.Type.ODP)
        span(op, a, b, 100)
        span(op, b, d, 100)
        span(op, a, d, 500)  # tempting single hop, but far longer

        body = api_as(Role.TENANT_OWNER, op).get(
            URL, {"from_point": a.id, "to_point": d.id}).json()
        assert [p["label"] for p in body["points"]] == ["A", "B", "D"]
        assert body["total_m"] == 200.0
        assert body["span_count"] == 2
        assert body["splice_count"] == 1  # B is the one intermediate splice

    def test_gps_source_snaps_to_nearest_point(self, db):
        op = OperatorFactory()
        a = pt(op, "A", -1.300, 36.800)
        b = pt(op, "B", -1.310, 36.800)
        span(op, a, b, 120)
        # A coordinate a hair from A must snap to A, then route A→B.
        body = api_as(Role.TENANT_TECHNICIAN, op).get(
            URL, {"from_lat": "-1.3001", "from_lng": "36.8001", "to_point": b.id}).json()
        assert body["from_snapped"]["point"]["label"] == "A"
        assert body["from_snapped"]["distance_m"] >= 0
        assert [p["label"] for p in body["points"]] == ["A", "B"]

    def test_route_to_a_customer_resolves_their_odp(self, db):
        op = OperatorFactory()
        a = pt(op, "A", -1.30, 36.80, type_=FibrePoint.Type.CABINET)
        odp = pt(op, "ODP-9", -1.31, 36.80, type_=FibrePoint.Type.ODP)
        span(op, a, odp, 90)
        router = RouterFactory(operator=op)
        client = PppoeClientFactory(
            operator=op, router=router, delivery_method="fibre", fibre_point=odp)

        body = api_as(Role.TENANT_OWNER, op).get(
            URL, {"from_point": a.id, "to_client": client.id}).json()
        assert body["points"][-1]["label"] == "ODP-9"
        assert body["total_m"] == 90.0

    def test_disconnected_points_are_404(self, db):
        op = OperatorFactory()
        a = pt(op, "A", -1.30, 36.80)
        b = pt(op, "B", -4.05, 39.66)  # no span between them
        r = api_as(Role.TENANT_OWNER, op).get(URL, {"from_point": a.id, "to_point": b.id})
        assert r.status_code == 404

    def test_customer_without_fibre_point_is_400(self, db):
        op = OperatorFactory()
        a = pt(op, "A", -1.30, 36.80)
        router = RouterFactory(operator=op)
        client = PppoeClientFactory(operator=op, router=router)  # no fibre_point
        r = api_as(Role.TENANT_OWNER, op).get(URL, {"from_point": a.id, "to_client": client.id})
        assert r.status_code == 400

    def test_is_tenant_scoped(self, db):
        """A point id from another tenant must not resolve."""
        a_op, b_op = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        mine = pt(a_op, "Mine", -1.30, 36.80)
        theirs = pt(b_op, "Theirs", -1.31, 36.80)
        r = api_as(Role.TENANT_OWNER, a_op).get(
            URL, {"from_point": mine.id, "to_point": theirs.id})
        assert r.status_code == 400  # theirs is invisible → "to_point not found"

    def test_requires_auth(self, db):
        assert APIClient().get(URL, {"from_point": 1, "to_point": 2}).status_code in (401, 403)
