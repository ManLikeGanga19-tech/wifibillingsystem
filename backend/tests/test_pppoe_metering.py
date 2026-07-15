"""PPPoE usage metering: turning session-relative counters into a cumulative monthly figure.

The subtle parts get the hard tests:
  * DELTA accumulation across polls (not read-the-total);
  * a RECONNECT that resets the router counter mid-cycle;
  * a session spanning the CYCLE BOUNDARY (prior-cycle bytes must not leak in);
  * offline detection;
  * FUP alerts firing ONCE per threshold per cycle, alert-only;
  * an unreachable router changing nothing.
"""

from datetime import date

import pytest
from django.utils import timezone

from apps.notifications.providers.dummy import DummyProvider
from apps.pppoe import metering
from apps.pppoe.models import Client, ClientUsage, PppoeSettings
from apps.provisioning.adapters.dummy import DummyAdapter

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, ServicePlanFactory

pytestmark = pytest.mark.django_db

GIB = 1024**3


def a_client(operator=None, router=None, cap_gb=None, **kw):
    operator = operator or OperatorFactory()
    router = router or RouterFactory(operator=operator, provisioning_backend="dummy")
    plan = ServicePlanFactory(operator=operator, data_cap_gb=cap_gb)
    return PppoeClientFactory(
        operator=operator, router=router, plan=plan,
        status=Client.Status.ACTIVE, **kw,
    )


def online(client, download, upload, ip="10.10.0.5", uptime="2h"):
    """Put the client in the router's active list with the given cumulative counters."""
    DummyAdapter.pppoe_active = {client.pppoe_username: (download, upload, ip, uptime, "AA:BB")}


# --- delta accumulation -----------------------------------------------------------------


def test_usage_accumulates_deltas_across_polls():
    client = a_client()

    online(client, download=GIB, upload=GIB // 2)  # 1 GB down, 0.5 up
    metering.poll_router(client.router)
    online(client, download=3 * GIB, upload=GIB)  # counter grew to 3 / 1
    metering.poll_router(client.router)

    usage = ClientUsage.objects.get(client=client)
    # First poll seeds the snapshot (delta 0); second adds (3-1) down, (1-0.5) up.
    assert usage.bytes_in == 2 * GIB
    assert usage.bytes_out == GIB // 2


def test_the_first_poll_seeds_the_snapshot_so_a_spanning_session_does_not_double_count():
    client = a_client()
    online(client, download=5 * GIB, upload=2 * GIB)  # already a long session

    metering.poll_router(client.router)

    usage = ClientUsage.objects.get(client=client)
    assert usage.bytes_in == 0  # we start counting from here, not the whole counter
    assert usage.snapshot_tx == 5 * GIB


def test_a_reconnect_that_resets_the_counter_is_handled():
    client = a_client()
    online(client, download=4 * GIB, upload=GIB)
    metering.poll_router(client.router)  # seed
    online(client, download=6 * GIB, upload=GIB)  # +2 down
    metering.poll_router(client.router)

    # Session drops and reconnects: counter restarts near zero.
    online(client, download=GIB // 2, upload=0)  # a fresh 0.5 GB session
    metering.poll_router(client.router)

    usage = ClientUsage.objects.get(client=client)
    # 2 GB from before + 0.5 GB from the new session = 2.5 GB down.
    assert usage.bytes_in == 2 * GIB + GIB // 2


def test_a_new_billing_cycle_starts_a_fresh_row():
    client = a_client(billing_day=15)

    # A poll "in June" — force the usage into a prior period, then poll again "in July".
    online(client, download=2 * GIB, upload=0)
    june = date(2026, 6, 15)
    metering.record(client, download=2 * GIB, upload=0, now=timezone.now())
    # Simulate the June row.
    ClientUsage.objects.filter(client=client).update(period_start=june, bytes_in=2 * GIB)

    # The live poll writes to the CURRENT cycle, a different row.
    metering.poll_router(client.router)

    periods = set(ClientUsage.objects.filter(client=client).values_list("period_start", flat=True))
    assert june in periods
    assert len(periods) == 2  # last month's row untouched, this month's fresh


# --- online / offline -------------------------------------------------------------------


def test_a_client_is_marked_online_with_live_details():
    client = a_client()
    online(client, download=GIB, upload=GIB, ip="10.9.9.9", uptime="5h30m")

    metering.poll_router(client.router)

    client.refresh_from_db()
    assert client.is_online is True
    assert client.wan_ip == "10.9.9.9"
    assert client.session_uptime == "5h30m"
    assert client.last_online_at is not None


def test_a_client_absent_from_the_router_is_marked_offline():
    client = a_client()
    online(client, download=GIB, upload=0)
    metering.poll_router(client.router)
    assert Client.objects.get(pk=client.pk).is_online is True

    DummyAdapter.pppoe_active = {}  # they dropped
    metering.poll_router(client.router)

    assert Client.objects.get(pk=client.pk).is_online is False


def test_an_unreachable_router_changes_nothing():
    client = a_client()
    online(client, download=GIB, upload=GIB)
    metering.poll_router(client.router)
    before = ClientUsage.objects.get(client=client).total_bytes

    # DummyAdapter raising unreachable: simulate by pointing at a mikrotik backend with no
    # reachable host is heavy; instead assert the guard by monkeypatching get_active_pppoe.

    class Boom:
        def get_active_pppoe(self):
            raise RuntimeError("unreachable")

    from apps.provisioning import adapters

    orig = adapters.get_adapter
    adapters.get_adapter = lambda r: Boom()
    try:
        assert metering.poll_router(client.router) == 0
    finally:
        adapters.get_adapter = orig

    assert ClientUsage.objects.get(client=client).total_bytes == before  # untouched


# --- FUP alerts -------------------------------------------------------------------------


def test_fup_alerts_fire_once_per_threshold_per_cycle():
    operator = OperatorFactory(slug="fup")
    PppoeSettings.objects.create(operator=operator, fup_alert_percents=[80, 100])
    client = a_client(operator=operator, cap_gb=10, phone="254700000001")
    DummyProvider.sent = []

    # Seed at zero (a fresh session), then grow the counter so usage ACCUMULATES.
    online(client, download=0, upload=0)
    metering.poll_router(client.router)

    # Counter climbs to 8.5 GB — over 80%, under 100%.
    online(client, download=8 * GIB, upload=GIB // 2)
    metering.poll_router(client.router)
    assert ClientUsage.objects.get(client=client).fup_alerted == [80]

    # A second poll at the same level must NOT re-alert.
    metering.poll_router(client.router)
    assert ClientUsage.objects.get(client=client).fup_alerted == [80]

    # Cross 100%.
    online(client, download=11 * GIB, upload=0)
    metering.poll_router(client.router)
    assert ClientUsage.objects.get(client=client).fup_alerted == [80, 100]


def test_an_uncapped_plan_never_fup_alerts():
    operator = OperatorFactory(slug="unlimited")
    PppoeSettings.objects.create(operator=operator, fup_alert_percents=[80])
    client = a_client(operator=operator, cap_gb=None, phone="254700000001")

    online(client, download=999 * GIB, upload=999 * GIB)
    metering.poll_router(client.router)

    assert ClientUsage.objects.get(client=client).fup_alerted == []


def test_fup_is_alert_only_speed_is_not_touched():
    """We alert; we do not throttle. The router push count stays zero."""
    operator = OperatorFactory(slug="noalter")
    PppoeSettings.objects.create(operator=operator, fup_alert_percents=[100])
    client = a_client(operator=operator, cap_gb=1, phone="254700000001")
    DummyAdapter.calls = []

    online(client, download=2 * GIB, upload=0)
    metering.poll_router(client.router)

    # No provisioning/profile change was pushed — FUP is notify-only.
    assert not any(c[0] in ("ensure_profile", "pppoe_create") for c in DummyAdapter.calls)


# --- period helper ----------------------------------------------------------------------


def test_current_period_start_tracks_the_billing_anniversary():
    client = a_client(billing_day=10)

    assert metering.current_period_start(client, date(2026, 7, 15)) == date(2026, 7, 10)
    assert metering.current_period_start(client, date(2026, 7, 5)) == date(2026, 6, 10)
    # January wraps to December.
    assert metering.current_period_start(client, date(2026, 1, 3)) == date(2025, 12, 10)


def test_metering_is_tenant_isolated():
    op_a = OperatorFactory(slug="a")
    op_b = OperatorFactory(slug="b")
    ca = a_client(operator=op_a)
    a_client(operator=op_b)

    online(ca, download=GIB, upload=0)
    metering.poll_router(ca.router)

    # Only A's client has usage; B's router was never polled here.
    assert ClientUsage.objects.filter(operator=op_a).count() == 1
    assert ClientUsage.objects.filter(operator=op_b).count() == 0


# --- the displays ------------------------------------------------------------------------


def test_the_client_api_exposes_live_status_and_cycle_usage():
    from rest_framework.test import APIClient

    from apps.accounts.models import Role

    from .factories import UserFactory

    operator = OperatorFactory(slug="disp")
    client = a_client(operator=operator, cap_gb=10)
    online(client, download=0, upload=0)
    metering.poll_router(client.router)
    online(client, download=2 * GIB, upload=GIB)  # 3 GB total
    metering.poll_router(client.router)

    api = APIClient()
    api.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    row = api.get(f"/api/v1/pppoe/clients/{client.id}/").json()

    assert row["is_online"] is True
    assert row["usage"]["gb_total"] == 3.0
    assert row["usage"]["cap_gb"] == 10
    assert row["usage"]["percent_used"] == 30.0


def test_the_dashboard_summary_aggregates_the_base():
    from rest_framework.test import APIClient

    from apps.accounts.models import Role

    from .factories import UserFactory

    operator = OperatorFactory(slug="dash")
    router = RouterFactory(operator=operator, provisioning_backend="dummy")
    heavy = a_client(operator=operator, router=router, cap_gb=5)
    a_client(operator=operator, router=router, cap_gb=100)

    online(heavy, download=0, upload=0)
    metering.poll_router(router)
    online(heavy, download=6 * GIB, upload=0)  # over its 5 GB cap
    metering.poll_router(router)

    api = APIClient()
    api.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    body = api.get("/api/v1/pppoe/usage-summary/").json()

    assert body["clients_active"] == 2
    assert body["online_now"] == 1
    assert body["over_fup"] == 1
    assert body["top_consumers"][0]["account_number"] == heavy.account_number
