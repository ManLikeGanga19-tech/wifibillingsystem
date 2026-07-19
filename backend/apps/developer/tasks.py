"""Deliver one webhook payload over HTTP, signed, with retries."""

import hashlib
import hmac
import json
import logging
import uuid

import httpx
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def sign(secret: str, body: bytes) -> str:
    """The value of the X-WIFIOS-Signature header — HMAC-SHA256 of the raw body, hex."""
    return hmac.new((secret or "").encode(), body, hashlib.sha256).hexdigest()


@shared_task(
    bind=True, autoretry_for=(Exception,), retry_backoff=True,
    retry_backoff_max=600, retry_jitter=True, max_retries=4,
)
def deliver_webhook(self, webhook_id: int, payload: dict):
    from .models import Webhook

    hook = Webhook.objects.filter(pk=webhook_id, is_active=True).first()
    if hook is None:
        return  # deleted / deactivated between queue and run — nothing to do

    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "WIFI.OS-Webhooks/1.0",
        "X-WIFIOS-Event": payload.get("event", ""),
        "X-WIFIOS-Delivery": str(uuid.uuid4()),
        "X-WIFIOS-Signature": f"sha256={sign(hook.secret, body)}",
    }

    try:
        resp = httpx.post(hook.url, content=body, headers=headers, timeout=10.0)
    except Exception as exc:
        _record(webhook_id, status=None, error=str(exc)[:255])
        raise  # network error — let Celery retry with backoff

    ok = resp.is_success
    _record(webhook_id, status=resp.status_code, error="" if ok else f"HTTP {resp.status_code}")
    # 5xx = their server hiccup, worth retrying; 4xx = they rejected it, retrying won't help.
    if resp.status_code >= 500:
        raise RuntimeError(f"webhook {webhook_id} returned {resp.status_code}")


def _record(webhook_id: int, *, status, error: str) -> None:
    from .models import Webhook

    Webhook.objects.filter(pk=webhook_id).update(
        last_delivered_at=timezone.now(), last_status=status, last_error=error
    )
