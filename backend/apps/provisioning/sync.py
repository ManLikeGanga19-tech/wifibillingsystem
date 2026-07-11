"""Router reconciliation: after a power-cut or reconnect, make the router's live
hotspot users match what the DB says should be active. Idempotent."""

import logging

from django.utils import timezone

from apps.core.services import audit

from .adapters import get_adapter
from .models import Session

logger = logging.getLogger(__name__)


def sync_router_sessions(router) -> dict:
    """Reconcile one router:
    - Sessions the DB thinks are ACTIVE but expired -> expire + remove from router.
    - ACTIVE sessions missing from the router -> re-provision (e.g. after reset/reboot).
    Returns a small report for logging/audit.
    """
    now = timezone.now()
    adapter = get_adapter(router)

    try:
        live = {s.username for s in adapter.get_active_sessions()}
    except Exception as exc:
        logger.warning("sync: cannot list active sessions on %s: %s", router, exc)
        live = None  # unknown — only handle expiries, don't guess re-provisioning

    db_active = Session.objects.filter(router=router, status=Session.Status.ACTIVE)
    report = {"reprovisioned": 0, "expired": 0, "checked": db_active.count()}

    for session in db_active.select_related("plan", "operator", "subscriber"):
        if session.expires_at <= now:
            # Overdue — belongs off the router
            session.status = Session.Status.EXPIRED
            session.save(update_fields=["status", "updated_at"])
            try:
                adapter.suspend_user(session)
            except Exception:
                pass
            report["expired"] += 1
            continue
        if live is not None and session.hotspot_username not in live:
            # Should be active but the router doesn't have it (rebooted/reset)
            try:
                adapter.activate_user(session)
                report["reprovisioned"] += 1
            except Exception as exc:
                logger.error("sync: re-provision failed for %s: %s", session.hotspot_username, exc)

    router.last_sync_at = now
    router.save(update_fields=["last_sync_at", "updated_at"])
    if report["reprovisioned"] or report["expired"]:
        audit("router_resynced", operator=router.operator, target=router, **report)
    return report
