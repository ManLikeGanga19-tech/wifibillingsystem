"""Router status alerts + outage compensation (Settings > Operator alerts).

Driven by the same health monitoring that flips a Router online/offline (see
tasks.check_router_health). On the EDGE — online->offline or offline->online — we:

  * text the ISP's team that a site dropped or recovered, if they asked to be told; and
  * track the outage as a RouterOutage window so that, on recovery, we can credit the
    downtime back to the affected PPPoE subscribers' expiry EXACTLY ONCE.

Everything here is opt-in per ISP and no-ops on the defaults, so an ISP who never opens the
page sees no behaviour change.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Below this, an outage is a blip (a single missed health check, a brief reconnect) and does
#: not credit anyone — chosen to sit just above the health-check cadence.
MIN_OUTAGE_SECONDS = 600  # 10 minutes
SECONDS_PER_DAY = 86_400


def _human_duration(seconds: int) -> str:
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    m = max(1, seconds // 60)
    return f"{m}m"


def on_router_offline(router) -> None:
    """A router just went from online to offline. Open an outage window (idempotent) and,
    if alerts are on, tell the team."""
    try:
        with transaction.atomic():
            from .models import RouterOutage

            _, created = RouterOutage.objects.get_or_create(
                router=router,
                ended_at__isnull=True,
                defaults={"started_at": timezone.now()},
            )
    except IntegrityError:
        created = False  # raced another worker to open it; that's fine
    if created:
        _alert(router, online=False)


def on_router_online(router) -> None:
    """A router just recovered. Close its open outage, compensate affected subscribers if the
    ISP opted in, and tell the team it's back."""
    from .models import RouterOutage

    outage = (
        RouterOutage.objects.filter(router=router, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    seconds = 0
    credited = 0
    if outage is not None:
        outage.ended_at = timezone.now()
        outage.save(update_fields=["ended_at"])
        seconds = outage.duration_seconds
        credited = compensate_outage(outage)
    _alert(router, online=True, seconds=seconds, credited=credited)


def compensate_outage(outage) -> int:
    """Credit the outage's downtime to every ACTIVE PPPoE client on the router, banking the
    seconds and rolling whole days onto next_due_date as they accrue. Idempotent (guarded by
    compensated_at). Returns how many clients were credited (0 if compensation is off, the
    outage was a blip, or nobody was affected)."""
    from apps.notifications.services import alert_settings_for

    router = outage.router
    if outage.compensated_at is not None:
        return 0
    if not alert_settings_for(router.operator).compensate_outages:
        return 0

    seconds = outage.duration_seconds
    if seconds < MIN_OUTAGE_SECONDS:
        return 0

    from apps.core.services import audit
    from apps.pppoe.models import Client

    credited = 0
    with transaction.atomic():
        clients = Client.objects.select_for_update().filter(
            operator=router.operator,
            router=router,
            status=Client.Status.ACTIVE,
            next_due_date__isnull=False,
        )
        for client in clients:
            client.outage_credit_seconds = (client.outage_credit_seconds or 0) + seconds
            fields = ["outage_credit_seconds", "updated_at"]
            if client.outage_credit_seconds >= SECONDS_PER_DAY:
                days = client.outage_credit_seconds // SECONDS_PER_DAY
                client.next_due_date = client.next_due_date + timedelta(days=days)
                client.outage_credit_seconds -= days * SECONDS_PER_DAY
                fields.append("next_due_date")
            client.save(update_fields=fields)
            credited += 1

        outage.compensated_at = timezone.now()
        outage.compensated_clients = credited
        outage.credited_seconds = seconds
        outage.save(update_fields=["compensated_at", "compensated_clients", "credited_seconds"])

    audit(
        "pppoe_outage_compensated",
        operator=router.operator,
        target=router,
        router=router.name,
        outage_id=outage.pk,
        seconds=seconds,
        clients=credited,
    )
    return credited


def _alert(router, *, online: bool, seconds: int = 0, credited: int = 0) -> None:
    from apps.notifications.services import alert_settings_for, send_operator_alert

    conf = alert_settings_for(router.operator)
    if not conf.router_alerts_enabled:
        return

    if online:
        body = f"WIFI.OS: {router.name} is BACK ONLINE"
        if seconds >= 60:
            body += f" after {_human_duration(seconds)} down"
        body += "."
        if credited:
            body += f" {credited} subscriber(s) credited the downtime."
    else:
        body = f"WIFI.OS: {router.name} is OFFLINE. We'll tell you when it recovers."

    send_operator_alert(router.operator, body, settings=conf)
