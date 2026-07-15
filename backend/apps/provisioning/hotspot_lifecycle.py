"""Captive-hotspot lifecycle: the behaviours behind Settings > Hotspot.

These read core.HotspotSettings per operator, so an ISP who leaves the defaults gets the
SAFE behaviour: the clock starts on purchase, and nothing is ever pruned. Pruning is
opt-in because it deletes customer records.
"""

import logging

from django.db.models import Max, Q
from django.utils import timezone

from apps.accounts.models import Subscriber
from apps.core.models import HotspotSettings

logger = logging.getLogger(__name__)


def hotspot_settings_for(operator) -> HotspotSettings:
    row, _ = HotspotSettings.objects.get_or_create(operator=operator)
    return row


def prune_dormant_subscribers() -> int:
    """Delete hotspot customers an ISP has opted to prune — the "auto-delete accounts
    unseen for N days" control.

    Conservative by design, because it removes a customer record:
      * only for operators that opted in (inactive_prune_days set);
      * only subscribers whose most recent session STARTED before the cutoff (or who never
        had one), so anyone recently active is safe;
      * never one with a session still inside its window — an online customer is never
        deleted mid-session;
      * never a BLOCKED subscriber — deleting them would silently lift the block on their
        next purchase.

    This is safe for the books: Session.subscriber and Transaction.subscriber are SET_NULL,
    and every transaction already stores its own `phone`, so the money trail survives the
    customer row going away.
    """
    now = timezone.now()
    pruned = 0
    configured = HotspotSettings.objects.filter(
        inactive_prune_days__isnull=False
    ).select_related("operator")
    for cfg in configured:
        cutoff = now - timezone.timedelta(days=cfg.inactive_prune_days)
        candidates = (
            Subscriber.objects.filter(operator=cfg.operator, is_blocked=False)
            .annotate(
                last_session=Max("sessions__starts_at"),
                # Any session whose window is still open right now.
                live=Max(
                    "sessions__expires_at",
                    filter=Q(sessions__expires_at__gt=now),
                ),
            )
            .filter(live__isnull=True)  # nobody currently online
            .filter(Q(last_session__lt=cutoff) | Q(last_session__isnull=True))
            .filter(created_at__lt=cutoff)  # never delete a just-created row with no sessions yet
        )
        count = candidates.count()
        if count:
            candidates.delete()
            pruned += count
            logger.info(
                "Pruned %d dormant hotspot subscribers for %s", count, cfg.operator.slug
            )
    return pruned
