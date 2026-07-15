"""Fixed-line lifecycle: how dormant accounts are pruned and subscribers reminded.

These are the behaviours behind Settings > PPPoE. They read PppoeSettings per operator, so
an ISP who leaves the defaults gets the SAFE behaviour: invoices auto-issued, nothing
pruned, no reminders sent.
"""

import logging

from django.db.models import F
from django.utils import timezone

from .models import Client, PppoeSettings

logger = logging.getLogger(__name__)


def settings_for(operator) -> PppoeSettings:
    row, _ = PppoeSettings.objects.get_or_create(operator=operator)
    return row


def prune_dormant_clients() -> int:
    """Delete DISABLED accounts an ISP has opted to prune.

    DELIBERATELY CONSERVATIVE, because deletion is irreversible and this is money-adjacent
    data:
      * only DISABLED clients (never active, suspended-but-owing, or pending installs);
      * only those untouched for the ISP's chosen number of days;
      * only those with NO invoices at all — a client who was ever billed is a financial
        record, and we archive by leaving them alone, never destroy the books to tidy a
        list. An ISP who truly wants a billed customer gone deletes them by hand.
    """
    from django.db.models import Count

    pruned = 0
    configured = PppoeSettings.objects.filter(inactive_prune_days__isnull=False)
    for cfg in configured.select_related("operator"):
        cutoff = timezone.now() - timezone.timedelta(days=cfg.inactive_prune_days)
        stale = (
            Client.objects.filter(
                operator=cfg.operator,
                status=Client.Status.DISABLED,
                updated_at__lt=cutoff,
            )
            .annotate(n_invoices=Count("invoices"))
            .filter(n_invoices=0)
        )
        count = stale.count()
        if count:
            stale.delete()
            pruned += count
            logger.info("Pruned %d dormant PPPoE clients for %s", count, cfg.operator.slug)
    return pruned


def remind_expiring_clients() -> int:
    """SMS subscribers ahead of their renewal, per the ISP's chosen lead times.

    Once per cycle: expiry_reminded_on records the next_due_date we last reminded for, so a
    renewal (which moves next_due_date) re-arms it and a second run the same day stays quiet.
    """
    from apps.notifications.models import Message
    from apps.notifications.services import send_sms

    now = timezone.now()
    today = timezone.localdate()
    reminded = 0

    configured = PppoeSettings.objects.exclude(pre_expiry_reminder_hours=[])
    for cfg in configured.select_related("operator"):
        hours = [h for h in cfg.pre_expiry_reminder_hours if isinstance(h, int)]
        if not hours:
            continue
        # The widest lead time defines the window we look ahead over; each client is
        # reminded once as it enters it.
        max_lead = max(hours)
        horizon = (now + timezone.timedelta(hours=max_lead)).date()

        # Not yet reminded for THIS cycle: expiry_reminded_on != the current next_due_date
        # (a renewal moves next_due_date, so the old marker no longer matches and re-arms).
        clients = (
            Client.objects.filter(
                operator=cfg.operator,
                status=Client.Status.ACTIVE,
                next_due_date__isnull=False,
                next_due_date__lte=horizon,
                next_due_date__gte=today,
            )
            .exclude(expiry_reminded_on=F("next_due_date"))
            .select_related("plan")
        )

        for client in clients.iterator():
            if client.phone:
                days = (client.next_due_date - today).days
                when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
                send_sms(
                    cfg.operator,
                    client.phone,
                    f"Hi {client.full_name.split(' ')[0]}, your {cfg.operator.name} "
                    f"internet renews {when} ({client.next_due_date:%d %b}). "
                    f"Pay to account {client.account_number} to stay connected.",
                    category=Message.Category.PPPOE,
                )
            client.expiry_reminded_on = client.next_due_date
            client.save(update_fields=["expiry_reminded_on", "updated_at"])
            reminded += 1
    return reminded
