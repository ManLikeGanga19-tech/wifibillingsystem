"""Live connections across every service type — one source of truth for "who is online now".

The dashboard KPI, the sidebar "Online Now" badge, and the Active Users page must all agree,
and adding a new service type (static, dynamic, Ruijie…) should be a single edit here rather
than a hunt through three endpoints. Hotspot liveness is an ACTIVE Session; PPPoE liveness is
an ACTIVE Client the metering poll has seen online. Every query is operator-scoped.
"""

from __future__ import annotations

# The service types we can currently see online. Extend this as new access methods land —
# add the count in live_connection_counts and the rows in live_connections, and every surface
# that reads them updates automatically.
SERVICE_TYPES = ("hotspot", "pppoe")


def live_connection_counts(operator) -> dict[str, int]:
    """How many connections are live right now, per service type. Sum for the headline."""
    from apps.pppoe.models import Client
    from apps.provisioning.models import Session

    return {
        "hotspot": Session.objects.filter(
            operator=operator, status=Session.Status.ACTIVE
        ).count(),
        "pppoe": Client.objects.filter(
            operator=operator, status=Client.Status.ACTIVE, is_online=True
        ).count(),
    }


def live_connections_total(operator) -> int:
    return sum(live_connection_counts(operator).values())


def live_counts_by_router(operator) -> dict[int, int]:
    """Live connections per router id, across service types — for the dashboard's per-router
    "active" column. Two grouped queries (no cross-join), summed by router, so a PPPoE-only
    router shows its online lines instead of a misleading zero."""
    from django.db.models import Count

    from apps.pppoe.models import Client
    from apps.provisioning.models import Session

    counts: dict[int, int] = {}
    hotspot = (
        Session.objects.filter(operator=operator, status=Session.Status.ACTIVE)
        .values("router")
        .annotate(n=Count("id"))
    )
    pppoe = (
        Client.objects.filter(
            operator=operator, status=Client.Status.ACTIVE, is_online=True
        )
        .values("router")
        .annotate(n=Count("id"))
    )
    for row in (*hotspot, *pppoe):
        counts[row["router"]] = counts.get(row["router"], 0) + row["n"]
    return counts


# A defensive cap: this feeds a live table, and an ISP with thousands online should still get
# a fast response. The counts (above) remain exact; only the row listing is bounded.
MAX_ROWS = 1000


def live_connections(operator, *, service_type: str = "all") -> list[dict]:
    """Normalised live-connection rows across service types, for the Active Users page.

    Every row shares a common core (service_type, identifier, name, plan, router, since, ip);
    hotspot rows carry their device/expiry extras, PPPoE rows their uptime — the frontend
    renders the shared columns and shows the extras where they exist."""
    rows: list[dict] = []
    if service_type in ("all", "hotspot"):
        rows += _hotspot_rows(operator)
    if service_type in ("all", "pppoe"):
        rows += _pppoe_rows(operator)
    # Longest-online first is the most useful default across types (most recent `since` last).
    rows.sort(key=lambda r: r["since"] or "", reverse=True)
    return rows[:MAX_ROWS]


def _hotspot_rows(operator) -> list[dict]:
    from apps.provisioning.models import Session

    sessions = (
        Session.objects.filter(operator=operator, status=Session.Status.ACTIVE)
        .select_related("plan", "router", "subscriber")
        .prefetch_related("devices")
    )
    rows = []
    for s in sessions:
        rows.append(
            {
                "service_type": "hotspot",
                "id": s.id,
                "identifier": s.hotspot_username,
                "name": s.subscriber.phone if s.subscriber_id else "",
                "plan_name": s.plan.name,
                "router_name": s.router.name,
                "status": s.status,
                "since": s.starts_at.isoformat() if s.starts_at else None,
                "uptime": "",  # hotspot has no router-reported uptime; derived from `since`
                "ip": s.ip_address,
                "mac_address": s.mac_address,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "provision_error": s.provision_error,
                "devices": [
                    {
                        "mac_address": d.mac_address,
                        "hostname": d.hostname,
                        "kind": d.kind,
                        "is_paying_device": d.is_paying_device,
                    }
                    for d in s.devices.all()
                ],
                "device_allowance": {
                    "general": s.plan.shared_users,
                    "tv": s.plan.tv_slots,
                },
            }
        )
    return rows


def _pppoe_rows(operator) -> list[dict]:
    from apps.pppoe.models import Client

    clients = Client.objects.filter(
        operator=operator, status=Client.Status.ACTIVE, is_online=True
    ).select_related("plan", "router")
    rows = []
    for c in clients:
        rows.append(
            {
                "service_type": "pppoe",
                "id": c.id,
                "identifier": c.account_number,
                "name": c.full_name,
                "plan_name": c.plan.name,
                "router_name": c.router.name,
                "status": c.status,
                "since": c.last_online_at.isoformat() if c.last_online_at else None,
                "uptime": c.session_uptime,
                "ip": c.wan_ip,
                "mac_address": "",
                "expires_at": None,
                "provision_error": "",
                "devices": [],
                "device_allowance": None,
            }
        )
    return rows
