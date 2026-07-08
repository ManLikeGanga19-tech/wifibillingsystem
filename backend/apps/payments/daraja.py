"""Safaricom Daraja API client (STK Push + STK Query).

Credentials resolve per-operator (SaaS-ready) and fall back to env settings (phase 1).
Sandbox and production differ only by DARAJA_BASE_URL and credentials.
"""

import base64
import logging
from datetime import datetime

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class DarajaError(Exception):
    pass


class DarajaClient:
    def __init__(self, operator=None):
        self.base_url = settings.DARAJA_BASE_URL.rstrip("/")
        self.consumer_key = (
            getattr(operator, "daraja_consumer_key", "") or settings.DARAJA_CONSUMER_KEY
        )
        self.consumer_secret = (
            getattr(operator, "daraja_consumer_secret", "") or settings.DARAJA_CONSUMER_SECRET
        )
        self.shortcode = getattr(operator, "mpesa_shortcode", "") or settings.DARAJA_SHORTCODE
        self.passkey = getattr(operator, "mpesa_passkey", "") or settings.DARAJA_PASSKEY
        if not (self.consumer_key and self.consumer_secret):
            raise DarajaError(
                "Daraja credentials missing. Set DARAJA_CONSUMER_KEY / DARAJA_CONSUMER_SECRET."
            )

    # -- auth -------------------------------------------------------------
    def _token(self) -> str:
        cache_key = f"daraja-token:{self.consumer_key[:8]}"
        token = cache.get(cache_key)
        if token:
            return token
        resp = httpx.get(
            f"{self.base_url}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(self.consumer_key, self.consumer_secret),
            timeout=30,
        )
        if resp.status_code != 200:
            raise DarajaError(f"Token request failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        token = data["access_token"]
        # Daraja tokens last 3600s; cache slightly shorter
        cache.set(cache_key, token, int(data.get("expires_in", 3600)) - 120)
        return token

    def _password(self, timestamp: str) -> str:
        return base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()

    def _post(self, path: str, payload: dict) -> dict:
        resp = httpx.post(
            f"{self.base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=30,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise DarajaError(f"Non-JSON response ({resp.status_code}): {resp.text[:200]}") from exc
        if resp.status_code != 200:
            raise DarajaError(
                f"{path} failed ({resp.status_code}): "
                f"{data.get('errorMessage') or data.get('ResponseDescription') or resp.text[:200]}"
            )
        return data

    # -- API --------------------------------------------------------------
    def stk_push(self, phone: str, amount: int, account_reference: str, description: str) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": (
                f"{settings.DARAJA_CALLBACK_BASE_URL.rstrip('/')}"
                f"/api/v1/payments/callback/{settings.DARAJA_CALLBACK_TOKEN}/"
            ),
            "AccountReference": account_reference[:12] or "WIFI",
            "TransactionDesc": description[:13] or "Wifi access",
        }
        data = self._post("/mpesa/stkpush/v1/processrequest", payload)
        if str(data.get("ResponseCode", "")) != "0":
            raise DarajaError(f"STK push rejected: {data}")
        return data

    def stk_query(self, checkout_request_id: str) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return self._post(
            "/mpesa/stkpushquery/v1/query",
            {
                "BusinessShortCode": self.shortcode,
                "Password": self._password(timestamp),
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            },
        )
