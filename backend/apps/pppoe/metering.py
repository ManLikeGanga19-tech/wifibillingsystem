"""PPPoE usage metering — turn the router's session-relative byte counters into a
cumulative, per-billing-cycle figure, and fire FUP alerts off it.

Source-agnostic by design: today the poll feeds it from MikroTik interface counters; a
future RADIUS Acct-Stop feed would call the same `record()` with the same numbers and
nothing downstream would change.

The two things that make this correct rather than naive:

  * DELTA, not total. The interface counter resets to zero every reconnect, so we add
    (current - snapshot), and treat current < snapshot as "reconnected, count current".
  * CYCLE BOUNDARIES. A session that spans a billing anniversary must not dump the previous
    cycle's bytes into the new one, so a freshly-created cycle row is seeded with the
    current counter (delta 0) — new bytes only accrue from there.
"""

import logging
from decimal import Decimal

from django.utils import timezone

from .models import Client, ClientUsage, PppoeSettings

logger = logging.getLogger(__name__)

GIB = 1024**3


def current_period_start(client, today=None):
    """First day of the billing cycle `today` falls in, for this client — the most recent
    occurrence of their billing day on or before today."""
    today = today or timezone.localdate()
    day = min(client.billing_day, 28)
    if today.day >= day:
        return today.replace(day=day)
    # Before the billing day this month → the cycle opened last month.
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return today.replace(year=year, month=month, day=day)


def _delta(current: int, snapshot: int) -> int:
    """Bytes since the last poll. A drop below the snapshot means the session reconnected
    and the router zeroed its counter, so the current value IS the delta."""
    return current - snapshot if current >= snapshot else current


def record(client, *, download: int, upload: int, ip: str = "", uptime: str = "",
           now=None) -> ClientUsage:
    """Fold one live observation of an ONLINE client into its cycle usage, and refresh the
    client's live-status cache."""
    now = now or timezone.now()
    period = current_period_start(client, timezone.localdate())

    usage, created = ClientUsage.objects.get_or_create(
        client=client,
        period_start=period,
        defaults={
            "operator": client.operator,
            # Seed the snapshot so a session spanning the cycle boundary does not dump its
            # prior-cycle bytes into this one.
            "snapshot_tx": download,
            "snapshot_rx": upload,
            "snapshot_at": now,
        },
    )
    if not created:
        usage.bytes_in += _delta(download, usage.snapshot_tx)
        usage.bytes_out += _delta(upload, usage.snapshot_rx)
        usage.snapshot_tx = download
        usage.snapshot_rx = upload
        usage.snapshot_at = now
        usage.save(update_fields=[
            "bytes_in", "bytes_out", "snapshot_tx", "snapshot_rx", "snapshot_at", "updated_at",
        ])

    # Live status cache.
    Client.objects.filter(pk=client.pk).update(
        is_online=True,
        last_online_at=now,
        wan_ip=ip or None,
        session_uptime=uptime or "",
        usage_synced_at=now,
    )
    return usage


def mark_offline(client, now=None) -> None:
    """A client we provisioned but did not see in /ppp/active. Leave usage untouched — we
    simply stop counting; the next time they appear the delta picks up from the snapshot."""
    if client.is_online:
        Client.objects.filter(pk=client.pk).update(
            is_online=False, usage_synced_at=now or timezone.now()
        )


def check_fup(client, usage, config: PppoeSettings) -> int:
    """Alert once per configured % threshold per cycle. Returns how many alerts fired.

    Alert-only by design — no throttle. Needs a data cap to have a percentage of; an
    unlimited plan never alerts."""
    cap_gb = client.plan.data_cap_gb
    thresholds = [p for p in (config.fup_alert_percents or []) if isinstance(p, int)]
    if not cap_gb or not thresholds:
        return 0

    used_gb = Decimal(usage.total_bytes) / Decimal(GIB)
    fired = 0
    alerted = set(usage.fup_alerted)
    for pct in sorted(thresholds):
        if pct in alerted:
            continue
        if used_gb >= Decimal(cap_gb) * Decimal(pct) / Decimal(100):
            _send_fup_sms(client, pct, used_gb, cap_gb)
            alerted.add(pct)
            usage.fup_alerted = sorted(alerted)
            fired += 1
    if fired:
        usage.save(update_fields=["fup_alerted", "updated_at"])
    return fired


def _send_fup_sms(client, pct: int, used_gb: Decimal, cap_gb: int) -> None:
    if not client.phone:
        return
    from apps.notifications.models import Message
    from apps.notifications.services import send_sms

    name = client.full_name.split(" ")[0] if client.full_name else "there"
    over = pct >= 100
    body = (
        f"Hi {name}, you have used {used_gb:.1f}GB of your {cap_gb}GB "
        f"{client.operator.name} plan"
        + (". You've reached your fair-use limit — speeds may be managed until your next "
           "cycle." if over else f" ({pct}%). Top up or upgrade to avoid slowdowns.")
    )
    send_sms(client.operator, client.phone, body, category=Message.Category.PPPOE)


# --- the poll ---------------------------------------------------------------------------


def poll_router(router, now=None) -> int:
    """Meter every active client on one router. Best-effort: an unreachable router is
    skipped whole, never zeroed. Returns clients observed online."""
    from apps.provisioning.adapters import get_adapter

    now = now or timezone.now()
    try:
        actives = {a.username: a for a in get_adapter(router).get_active_pppoe()}
    except Exception:
        logger.warning("pppoe usage: %s unreachable", router.name)
        return 0

    clients = Client.objects.filter(
        router=router, status=Client.Status.ACTIVE
    ).select_related("plan", "operator")

    settings_cache: dict[int, PppoeSettings] = {}
    online = 0
    for client in clients.iterator():
        live = actives.get(client.pppoe_username)
        if live is None:
            mark_offline(client, now)
            continue
        online += 1
        usage = record(
            client, download=live.bytes_in, upload=live.bytes_out,
            ip=live.ip_address, uptime=live.uptime, now=now,
        )
        cfg = settings_cache.get(client.operator_id)
        if cfg is None:
            cfg, _ = PppoeSettings.objects.get_or_create(operator=client.operator)
            settings_cache[client.operator_id] = cfg
        check_fup(client, usage, cfg)
    return online


def poll_all() -> int:
    """Beat body (every 5 min): meter every router that has active PPPoE clients."""
    from apps.provisioning.models import Router

    router_ids = (
        Client.objects.filter(status=Client.Status.ACTIVE)
        .values_list("router_id", flat=True)
        .distinct()
    )
    total = 0
    for router in Router.objects.filter(id__in=list(router_ids), is_active=True):
        total += poll_router(router)
    return total
