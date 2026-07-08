"""WhatsApp Business Cloud API (Meta).

NOTE: business-initiated messages outside the 24h customer service window must
use a pre-approved template. Free-text works only inside that window; expect
error 131047 otherwise and prefer SMS for cold bulk sends.
"""

import httpx
from django.conf import settings

from .base import MessageProvider, ProviderError, SendResult


class WhatsAppCloud(MessageProvider):
    def __init__(self):
        if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
            raise ProviderError("WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID not configured")
        self.url = (
            f"{settings.WHATSAPP_API_BASE.rstrip('/')}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        self.token = settings.WHATSAPP_TOKEN

    def send(self, to_phone: str, body: str) -> SendResult:
        resp = httpx.post(
            self.url,
            json={
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "text",
                "text": {"body": body},
            },
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )
        is_json = resp.headers.get("content-type", "").startswith("application/json")
        data = resp.json() if is_json else {}
        if resp.status_code == 200 and data.get("messages"):
            return SendResult(ok=True, provider_ref=data["messages"][0].get("id", ""))
        err = (data.get("error") or {}).get("message", f"HTTP {resp.status_code}")
        return SendResult(ok=False, error=str(err)[:255])
