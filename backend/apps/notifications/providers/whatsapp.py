"""WhatsApp Business Cloud API (Meta).

NOTE: business-initiated messages outside the 24h customer service window must
use a pre-approved template. Free-text works only inside that window; expect
error 131047 otherwise and prefer SMS for cold bulk sends.

Credentials are passed in — there is no platform WhatsApp account (we hold no Meta
business identity on an ISP's behalf), so in practice this only ever runs on an ISP's
own credentials.
"""

import httpx
from django.conf import settings

from .base import MessageProvider, ProviderError, SendResult


class WhatsAppCloud(MessageProvider):
    def __init__(self, phone_number_id: str, token: str, api_base: str = ""):
        if not (token and phone_number_id):
            raise ProviderError("WhatsApp token / phone number ID is not configured")
        base = (api_base or settings.WHATSAPP_API_BASE).rstrip("/")
        self.url = f"{base}/{phone_number_id}/messages"
        self.token = token

    def send(self, message) -> SendResult:
        resp = httpx.post(
            self.url,
            json={
                "messaging_product": "whatsapp",
                "to": message.to_phone,
                "type": "text",
                "text": {"body": message.body},
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
