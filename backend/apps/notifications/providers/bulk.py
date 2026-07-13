"""The bring-your-own SMS gateways.

Each is a thin HTTP call. They differ only in where the credential goes and what "it
worked" looks like in the response — which is exactly why the send path treats them all
as a MessageProvider and never learns their names.

A word on trusting these: every provider below is spoken to over its documented public
API, but a bulk-SMS account has settings we cannot see from here (an unapproved sender
ID, a sub-account with no balance, an IP allowlist). Those fail at the PROVIDER, not at
us, and they fail quietly. That is what "Send test" in the console is for: it drives the
real gateway with the real key and shows the provider's own error back to the ISP before
a customer ever depends on it.
"""

import httpx

from .base import MessageProvider, ProviderError, SendResult

TIMEOUT = 30


def _need(creds: dict, *keys: str) -> None:
    missing = [k for k in keys if not creds.get(k)]
    if missing:
        raise ProviderError(f"Missing credential: {', '.join(missing)}")


class MobileSasaSMS(MessageProvider):
    """MobileSasa (Kenya) — bearer token, JSON."""

    def __init__(self, **creds):
        _need(creds, "api_token", "sender_id")
        self.token = creds["api_token"]
        self.sender_id = creds["sender_id"]

    def send(self, message) -> SendResult:
        resp = httpx.post(
            "https://api.mobilesasa.com/v1/send/message",
            json={
                "senderID": self.sender_id,
                "message": message.body,
                "phone": message.to_phone,
            },
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
        return _json_result(resp, ok_key="status", ref_key="messageId")


class BlessedTextsSMS(MessageProvider):
    """BlessedTexts (Kenya)."""

    def __init__(self, **creds):
        _need(creds, "api_key", "sender_id")
        self.api_key = creds["api_key"]
        self.sender_id = creds["sender_id"]

    def send(self, message) -> SendResult:
        resp = httpx.post(
            "https://api.blessedtexts.com/api/sms/v1/sendsms",
            json={
                "api_key": self.api_key,
                "sender_id": self.sender_id,
                "message": message.body,
                "phone": message.to_phone,
            },
            timeout=TIMEOUT,
        )
        return _json_result(resp, ok_key="status", ref_key="message_id")


class BongaSMS(MessageProvider):
    """Bonga SMS (Kenya) — form-encoded, client id + key + secret."""

    def __init__(self, **creds):
        _need(creds, "client_id", "api_key", "api_secret", "service_id")
        self.creds = creds

    def send(self, message) -> SendResult:
        resp = httpx.post(
            "https://bongasms.co.ke/api/send-sms-v1",
            data={
                "apiClientID": self.creds["client_id"],
                "key": self.creds["api_key"],
                "secret": self.creds["api_secret"],
                "txtMessage": message.body,
                "MSISDN": message.to_phone,
                "serviceID": self.creds["service_id"],
            },
            timeout=TIMEOUT,
        )
        return _json_result(resp, ok_key="status", ref_key="unique_id")


class HostPinnacleSMS(MessageProvider):
    """BulkSMS by Host Pinnacle (Kenya)."""

    def __init__(self, **creds):
        _need(creds, "user_id", "password", "sender_id")
        self.creds = creds

    def send(self, message) -> SendResult:
        resp = httpx.post(
            "https://api.hostpinnacle.co.ke/SMSApi/send",
            data={
                "userid": self.creds["user_id"],
                "password": self.creds["password"],
                "senderid": self.creds["sender_id"],
                "mobile": message.to_phone,
                "msg": message.body,
                "msgType": "text",
                "duplicatecheck": "true",
                "output": "json",
                "sendMethod": "quick",
            },
            timeout=TIMEOUT,
        )
        return _json_result(resp, ok_key="status", ref_key="transactionId")


class TwilioSMS(MessageProvider):
    """Twilio — basic auth, form-encoded. `whatsapp` prefixes the numbers for WA."""

    def __init__(self, *, whatsapp: bool = False, **creds):
        _need(creds, "account_sid", "auth_token", "from_number")
        self.sid = creds["account_sid"]
        self.token = creds["auth_token"]
        self.from_number = creds["from_number"]
        self.whatsapp = whatsapp

    def send(self, message) -> SendResult:
        to = f"+{message.to_phone.lstrip('+')}"
        sender = self.from_number
        if self.whatsapp:
            to = f"whatsapp:{to}"
            if not sender.startswith("whatsapp:"):
                sender = f"whatsapp:{sender}"
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            data={"To": to, "From": sender, "Body": message.body},
            auth=(self.sid, self.token),
            timeout=TIMEOUT,
        )
        data = _body(resp)
        if resp.status_code in (200, 201) and data.get("sid"):
            return SendResult(ok=True, provider_ref=str(data["sid"]))
        err = data.get("message") or f"HTTP {resp.status_code}"
        return SendResult(ok=False, error=str(err)[:255])


class InfobipSMS(MessageProvider):
    """Infobip — per-account base URL, App-key auth."""

    def __init__(self, *, whatsapp: bool = False, **creds):
        _need(creds, "base_url", "api_key")
        host = creds["base_url"].replace("https://", "").replace("http://", "").strip("/")
        self.whatsapp = whatsapp
        self.url = (
            f"https://{host}/whatsapp/1/message/text"
            if whatsapp
            else f"https://{host}/sms/2/text/advanced"
        )
        self.api_key = creds["api_key"]
        self.sender = creds.get("sender") or creds.get("sender_id") or ""

    def send(self, message) -> SendResult:
        if self.whatsapp:
            payload = {
                "from": self.sender,
                "to": message.to_phone,
                "content": {"text": message.body},
            }
        else:
            payload = {
                "messages": [
                    {
                        "destinations": [{"to": message.to_phone}],
                        "text": message.body,
                        **({"from": self.sender} if self.sender else {}),
                    }
                ]
            }
        resp = httpx.post(
            self.url,
            json=payload,
            headers={
                "Authorization": f"App {self.api_key}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
        )
        data = _body(resp)
        if resp.status_code in (200, 201):
            messages = data.get("messages")
            ref = ""
            if isinstance(messages, list) and messages:
                ref = str(messages[0].get("messageId", ""))
            elif data.get("messageId"):
                ref = str(data["messageId"])
            return SendResult(ok=True, provider_ref=ref)
        err = (data.get("requestError") or {}).get("serviceException", {}).get("text")
        return SendResult(ok=False, error=str(err or f"HTTP {resp.status_code}")[:255])


class ApiwapWhatsApp(MessageProvider):
    """Apiwap / Notiva — WhatsApp Business resellers with the same simple shape."""

    BASE = "https://api.apiwap.com/api/v1/whatsapp/send"

    def __init__(self, **creds):
        _need(creds, "api_key", "sender")
        self.api_key = creds["api_key"]
        self.sender = creds["sender"]

    def send(self, message) -> SendResult:
        resp = httpx.post(
            self.BASE,
            json={"from": self.sender, "to": message.to_phone, "message": message.body},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=TIMEOUT,
        )
        return _json_result(resp, ok_key="status", ref_key="id")


class NotivaWhatsApp(ApiwapWhatsApp):
    BASE = "https://api.notiva.net/api/v1/whatsapp/send"


# --- shared response handling ----------------------------------------------------------


def _body(resp) -> dict:
    if not resp.headers.get("content-type", "").startswith("application/json"):
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_result(resp, *, ok_key: str, ref_key: str) -> SendResult:
    """Most of these gateways answer with {status: true/…, <ref>: "..."} and put the
    reason for a rejection in `message`. Anything we cannot read as success is a failure —
    reporting a send we are not sure about is how a customer ends up not knowing their
    payment worked."""
    data = _body(resp)
    if resp.status_code not in (200, 201):
        detail = data.get("message") or resp.text[:180]
        return SendResult(ok=False, error=f"HTTP {resp.status_code}: {detail}"[:255])

    flag = data.get(ok_key)
    ok = flag is True or str(flag).lower() in {"true", "success", "ok", "1", "200"}
    if ok:
        return SendResult(ok=True, provider_ref=str(data.get(ref_key, "")))
    return SendResult(ok=False, error=str(data.get("message") or data or "Rejected")[:255])
