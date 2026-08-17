"""The Map page data endpoint — tenant-scoped points for towers, clients and routers.

A map of customers' home coordinates is sensitive PII, so the tests pin the two properties
that matter: only THIS operator's points come back, and a record without coordinates is
counted as 'unplaced' rather than dropped (so nothing is silently invisible)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.models import Tower

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    RouterFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/map/points/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _tower(op, lat, lng, name="T"):
    return Tower.objects.create(operator=op, name=name, gps_lat=lat, gps_lng=lng)


class TestMapPoints:
    def test_returns_placed_points_per_layer(self):
        from apps.ops.models import Lead

        op = OperatorFactory()
        _tower(op, Decimal("-1.30"), Decimal("36.80"))
        RouterFactory(operator=op, name="R1", gps_lat=Decimal("-1.31"), gps_lng=Decimal("36.79"))
        PppoeClientFactory(operator=op, gps_lat=Decimal("-1.32"), gps_lng=Decimal("36.81"))
        Lead.objects.create(operator=op, name="Prospect", status=Lead.Status.NEW,
                            gps_lat=Decimal("-1.33"), gps_lng=Decimal("36.82"))

        body = owner(op).get(URL).json()
        assert body["counts"] == {"towers": 1, "clients": 1, "routers": 1, "leads": 1, "fibre": 0}
        assert body["center"] is not None
        assert body["layers"]["clients"][0]["status"]  # carries status for colouring
        assert body["layers"]["leads"][0]["label"] == "Prospect"

    def test_dead_leads_are_not_plotted(self):
        from apps.ops.models import Lead

        op = OperatorFactory()
        Lead.objects.create(operator=op, name="Won", status=Lead.Status.CONVERTED,
                            gps_lat=Decimal("-1.3"), gps_lng=Decimal("36.8"))
        Lead.objects.create(operator=op, name="Dead", status=Lead.Status.LOST,
                            gps_lat=Decimal("-1.3"), gps_lng=Decimal("36.8"))
        Lead.objects.create(operator=op, name="Live", status=Lead.Status.NEW,
                            gps_lat=Decimal("-1.3"), gps_lng=Decimal("36.8"))
        body = owner(op).get(URL).json()
        # only the open pipeline (new/contacted) is "where to expand"
        assert [ld["label"] for ld in body["layers"]["leads"]] == ["Live"]

    def test_records_without_coords_are_unplaced_not_dropped(self):
        op = OperatorFactory()
        # A shared PLACED router, so the client factory doesn't auto-mint extra unplaced ones.
        placed = RouterFactory(operator=op, gps_lat=Decimal("-1.3"), gps_lng=Decimal("36.8"))
        PppoeClientFactory(operator=op, router=placed,
                           gps_lat=Decimal("-1.3"), gps_lng=Decimal("36.8"))
        PppoeClientFactory(operator=op, router=placed, gps_lat=None, gps_lng=None)  # unplaced
        RouterFactory(operator=op, gps_lat=None, gps_lng=None)  # unplaced router

        body = owner(op).get(URL).json()
        assert body["counts"]["clients"] == 1
        assert body["unplaced"]["clients"] == 1
        assert body["counts"]["routers"] == 1
        assert body["unplaced"]["routers"] == 1

    def test_is_tenant_scoped(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        _tower(a, Decimal("-1.30"), Decimal("36.80"), name="A-tower")
        _tower(b, Decimal("-4.05"), Decimal("39.66"), name="B-tower")

        body = owner(a).get(URL).json()
        labels = [t["label"] for t in body["layers"]["towers"]]
        assert labels == ["A-tower"]  # B's tower never appears

    def test_empty_operator_has_null_center(self):
        body = owner(OperatorFactory()).get(URL).json()
        assert body["center"] is None
        assert body["counts"] == {"towers": 0, "clients": 0, "routers": 0, "leads": 0, "fibre": 0}

    def test_requires_auth(self):
        assert APIClient().get(URL).status_code in (401, 403)


class TestBusinessLocation:
    URL = "/api/v1/map/business-location/"

    def test_set_and_read_back(self):
        op = OperatorFactory()
        c = owner(op)
        r = c.post(self.URL, {"gps_lat": "-1.29", "gps_lng": "36.81"}, format="json")
        assert r.status_code == 200, r.content
        op.refresh_from_db()
        assert float(op.gps_lat) == -1.29 and float(op.gps_lng) == 36.81
        assert c.get(self.URL).json()["gps_lat"] == -1.29

    def test_business_location_is_the_map_center(self):
        op = OperatorFactory(gps_lat=Decimal("-1.30"), gps_lng=Decimal("36.80"))
        # a stray asset far away must NOT pull the centre off the business location
        RouterFactory(operator=op, gps_lat=Decimal("-4.05"), gps_lng=Decimal("39.66"))
        body = owner(op).get(URL).json()
        assert body["business_location"] == {"lat": -1.3, "lng": 36.8}
        assert body["center"] == {"lat": -1.3, "lng": 36.8}

    def test_out_of_range_rejected(self):
        r = owner(OperatorFactory()).post(
            self.URL, {"gps_lat": "999", "gps_lng": "0"}, format="json")
        assert r.status_code == 400

    def test_no_business_location_falls_back_to_null_center(self):
        body = owner(OperatorFactory()).get(URL).json()
        assert body["business_location"] is None
        assert body["center"] is None  # client then uses the device location
