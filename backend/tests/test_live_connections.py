"""Live connections span every service type. The dashboard KPI, the sidebar badge, and the
Active Users page must all count hotspot AND PPPoE (and later static/Ruijie) — not just
hotspot sessions. These pin that so a future service type can't quietly go uncounted."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.live import live_connection_counts, live_connections
from apps.pppoe.models import Client

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    SessionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _online_pppoe(op, **kw):
    return PppoeClientFactory(operator=op, status=Client.Status.ACTIVE, is_online=True, **kw)


class TestCounts:
    def test_counts_span_hotspot_and_pppoe(self):
        op = OperatorFactory()
        SessionFactory(operator=op)  # active hotspot session
        SessionFactory(operator=op)
        _online_pppoe(op)  # one online PPPoE line

        counts = live_connection_counts(op)
        assert counts == {"hotspot": 2, "pppoe": 1}

    def test_offline_or_suspended_pppoe_is_not_live(self):
        op = OperatorFactory()
        _online_pppoe(op)  # counts
        PppoeClientFactory(operator=op, status=Client.Status.ACTIVE, is_online=False)  # not
        PppoeClientFactory(operator=op, status=Client.Status.SUSPENDED, is_online=True)  # not

        assert live_connection_counts(op)["pppoe"] == 1

    def test_counts_are_tenant_scoped(self):
        mine = OperatorFactory(slug="mine")
        theirs = OperatorFactory(slug="theirs")
        SessionFactory(operator=theirs)
        _online_pppoe(theirs)
        assert live_connection_counts(mine) == {"hotspot": 0, "pppoe": 0}


class TestRows:
    def test_rows_are_normalised_across_types(self):
        op = OperatorFactory()
        SessionFactory(operator=op)
        _online_pppoe(op, full_name="Jane Line")

        rows = live_connections(op)
        kinds = {r["service_type"] for r in rows}
        assert kinds == {"hotspot", "pppoe"}
        # every row carries the shared core the unified table renders
        for r in rows:
            assert set(r) >= {"service_type", "identifier", "name", "plan_name",
                              "router_name", "status", "since", "ip"}
        pppoe = next(r for r in rows if r["service_type"] == "pppoe")
        assert pppoe["name"] == "Jane Line"

    def test_type_filter(self):
        op = OperatorFactory()
        SessionFactory(operator=op)
        _online_pppoe(op)
        pppoe = live_connections(op, service_type="pppoe")
        hotspot = live_connections(op, service_type="hotspot")
        assert {r["service_type"] for r in pppoe} == {"pppoe"}
        assert {r["service_type"] for r in hotspot} == {"hotspot"}


class TestEndpoints:
    def test_live_connections_endpoint(self):
        op = OperatorFactory()
        SessionFactory(operator=op)
        _online_pppoe(op)

        body = staff(op).get("/api/v1/live-connections/").json()
        assert body["counts"] == {"hotspot": 1, "pppoe": 1}
        assert len(body["results"]) == 2

    def test_dashboard_active_sessions_spans_types(self):
        op = OperatorFactory()
        SessionFactory(operator=op)
        _online_pppoe(op)

        kpis = staff(op).get("/api/v1/stats/").json()["kpis"]
        assert kpis["active_sessions"] == 2
        assert kpis["active_by_service"] == {"hotspot": 1, "pppoe": 1}

    def test_nav_active_users_spans_types(self):
        op = OperatorFactory()
        SessionFactory(operator=op)
        _online_pppoe(op)
        assert staff(op).get("/api/v1/nav/").json()["active_users"] == 2
