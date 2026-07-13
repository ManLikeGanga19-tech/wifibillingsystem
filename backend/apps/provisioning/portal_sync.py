"""Pushing a new captive-portal address onto an ISP's routers.

When an ISP changes their subdomain, every router of theirs is still redirecting
customers to the OLD address. Until this lands, a customer connecting to their WiFi is
sent somewhere the ISP has moved out of — which is why the old subdomain keeps resolving
for a grace period (core.domains.GRACE_DAYS). This is the work that closes that gap.

The honest part: a router that is OFFLINE cannot be told anything. We record that it
failed and show the ISP exactly which routers are still on the old address, rather than
reporting a clean success and letting them discover the truth from a customer.
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, max_retries=5)
def push_portal_to_router(self, router_id: int, portal_url: str):
    """Repoint one router. Retries with backoff — a router that is merely rebooting
    should not need a human to notice."""
    from .adapters import get_adapter
    from .models import Router

    router = Router.objects.get(pk=router_id)
    try:
        get_adapter(router).push_portal(portal_url)
    except Exception as exc:
        Router.objects.filter(pk=router_id).update(portal_sync_error=str(exc)[:255])
        logger.warning("portal push failed for router %s: %s", router_id, exc)
        raise  # let the retry policy do its work

    Router.objects.filter(pk=router_id).update(
        portal_url=portal_url,
        portal_synced_at=timezone.now(),
        portal_sync_error="",
    )
    logger.info("router %s now points at %s", router_id, portal_url)


def refresh_portal(operator) -> int:
    """Queue a portal push for every one of this ISP's routers. Returns how many.

    Every router, not just the ones we believe are online: "online" is a stale belief the
    moment we read it, and the task retries anyway. A router that is genuinely down will
    exhaust its retries and be shown to the ISP as unsynced.
    """
    from apps.core.domains import portal_url_for

    from .models import Router

    portal_url = portal_url_for(operator)
    routers = Router.objects.filter(operator=operator, is_active=True)
    for router in routers:
        # Clear the stale success marker first: until the push lands, this router is NOT
        # on the new address, and the console must not claim otherwise.
        Router.objects.filter(pk=router.pk).update(portal_synced_at=None, portal_sync_error="")
        push_portal_to_router.delay(router.pk, portal_url)
    return routers.count()
