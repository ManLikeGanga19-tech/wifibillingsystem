"""Africa's Talking SMS. Username 'sandbox' automatically targets their sandbox API.

Credentials are passed IN, never read from settings here: the same class serves the
platform's account and an ISP's own account (see providers.resolve_provider). A provider
that reached for global settings could only ever send as one sender.
"""

import httpx

from .base import MessageProvider, ProviderError, SendResult


class AfricasTalkingSMS(MessageProvider):
    def __init__(self, username: str, api_key: str, sender_id: str = ""):
        if not api_key:
            raise ProviderError("No Africa's Talking API key is configured")
        self.username = username or "sandbox"
        self.api_key = api_key
        self.sender_id = sender_id
        host = (
            "https://api.sandbox.africastalking.com"
            if self.username == "sandbox"
            else "https://api.africastalking.com"
        )
        self.url = f"{host}/version1/messaging"

    def send(self, message) -> SendResult:
        data = {"username": self.username, "to": f"+{message.to_phone}", "message": message.body}
        if self.sender_id:
            data["from"] = self.sender_id
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
