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


#: Paybill and Till are DIFFERENT Daraja transaction types. Sending a till payment as
#: CustomerPayBillOnline does not fail loudly — Safaricom rejects it in a way that looks
#: like a customer cancellation, so the ISP would blame their subscribers.
PAYBILL = "paybill"
TILL = "till"
TRANSACTION_TYPES = {
    PAYBILL: "CustomerPayBillOnline",
    TILL: "CustomerBuyGoodsOnline",
}


class DarajaClient:
    """Safaricom Daraja, on WHOEVER's shortcode.

    Credentials are passed IN. The platform's own paybill (the aggregator path) and an
    ISP's own shortcode (instant settlement to them) are the same API with different keys,
    so they are the same class — a client that reached for `settings` could only ever
    collect money into one account, which is the very thing this refactor exists to end.
    """

    def __init__(
        self,
        *,
        consumer_key: str = "",
        consumer_secret: str = "",
        shortcode: str = "",
        passkey: str = "",
        collection_method: str = PAYBILL,
        base_url: str = "",
    ):
        self.base_url = (base_url or settings.DARAJA_BASE_URL).rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.shortcode = shortcode
        self.passkey = passkey
        self.collection_method = collection_method
        if not (self.consumer_key and self.consumer_secret):
            raise DarajaError("Daraja consumer key/secret are not configured.")
        if not (self.shortcode and self.passkey):
            raise DarajaError("Daraja shortcode/passkey are not configured.")

    @classmethod
    def for_platform(cls) -> "DarajaClient":
        """Danamo's own paybill — the aggregator path, and how ISPs top us up."""
        return cls(
            consumer_key=settings.DARAJA_CONSUMER_KEY,
            consumer_secret=settings.DARAJA_CONSUMER_SECRET,
            shortcode=settings.DARAJA_SHORTCODE,
            passkey=settings.DARAJA_PASSKEY,
            collection_method=PAYBILL,
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
    def stk_push(
        self,
        phone: str,
        amount: int,
        account_reference: str,
        description: str,
        callback_path: str = "",
    ) -> dict:
        """`callback_path` lets a caller route the result somewhere other than the
        subscriber-payment callback. An ISP topping up their own platform account is money
        flowing the OPPOSITE way (they pay us), and landing it in the subscriber handler
        would credit an ISP for a payment no customer made."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        path = callback_path or (
            f"/api/v1/payments/callback/{settings.DARAJA_CALLBACK_TOKEN}/"
        )
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            # Paybill vs Till is not cosmetic — see TRANSACTION_TYPES.
            "TransactionType": TRANSACTION_TYPES.get(
                self.collection_method, TRANSACTION_TYPES[PAYBILL]
            ),
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": f"{settings.DARAJA_CALLBACK_BASE_URL.rstrip('/')}{path}",
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
