"""emit_event — the single call every lifecycle point uses to fan an event out to webhooks.

Two hard rules, because a webhook is other people's flaky HTTP endpoint:
  * fire on COMMIT — never deliver an event for a transaction that then rolls back;
  * swallow everything here — a webhook lookup problem must never break the action (a payment, a
    suspension) that triggered it. The actual HTTP call is a retrying Celery task.
"""

import logging

from django.db import transaction
from django.utils import timezone

from .events import EVENT_KEYS

logger = logging.getLogger(__name__)


def emit_event(operator, event: str, data: dict | None = None) -> None:
    """Queue signed delivery of `event` to every active webhook of `operator` subscribed to it."""
    if operator is None or event not in EVENT_KEYS:
        return
    from .models import Webhook

    try:
        hooks = list(Webhook.objects.filter(operator=operator, is_active=True))
    except Exception:
        logger.exception("webhook lookup failed for %s/%s", getattr(operator, "slug", "?"), event)
        return

    targets = [h.pk for h in hooks if event in (h.events or [])]
    if not targets:
        return

    payload = {
        "event": event,
        "created_at": timezone.now().isoformat(),
        "operator": operator.slug,
        "data": data or {},
    }
    from .tasks import deliver_webhook

    for hid in targets:
        transaction.on_commit(lambda hid=hid: deliver_webhook.delay(hid, payload))
