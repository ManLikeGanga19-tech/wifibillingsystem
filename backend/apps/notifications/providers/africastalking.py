"""Africa's Talking SMS. Username 'sandbox' automatically targets their sandbox API."""

import httpx
from django.conf import settings

from .base import MessageProvider, ProviderError, SendResult


class AfricasTalkingSMS(MessageProvider):
    def __init__(self):
        self.username = settings.AT_USERNAME
        self.api_key = settings.AT_API_KEY
        if not self.api_key:
            raise ProviderError("AT_API_KEY is not configured")
        host = (
            "https://api.sandbox.africastalking.com"
            if self.username == "sandbox"
            else "https://api.africastalking.com"
        )
        self.url = f"{host}/version1/messaging"

    def send(self, message) -> SendResult:
        data = {"username": self.username, "to": f"+{message.to_phone}", "message": message.body}
        if settings.AT_SENDER_ID:
            data["from"] = settings.AT_SENDER_ID
        resp = httpx.post(
            self.url,
            data=data,
            headers={"apiKey": self.api_key, "Accept": "application/json"},
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return SendResult(ok=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        sms_data = resp.json().get("SMSMessageData", {})
        recipients = sms_data.get("Recipients", [])
        if not recipients:
            return SendResult(ok=False, error=sms_data.get("Message", "No recipients"))
        r = recipients[0]
        if r.get("status") == "Success":
            return SendResult(ok=True, provider_ref=r.get("messageId", ""))
        return SendResult(ok=False, error=str(r.get("status", "Unknown failure")))
