"""M-Pesa via Daraja — on our paybill (aggregator) or on the ISP's own (instant).

Same API, different keys, so one adapter with two credential sources. The only thing that
really differs is where the money lands, and that is exactly what `settlement` records.
"""

import logging
from decimal import Decimal

from django.conf import settings

from ..daraja import DarajaClient, DarajaError
from .base import ChargeResult, GatewayError, PaymentEvent, PaymentGateway
from .catalog import DIRECT, PLATFORM

logger = logging.getLogger(__name__)

#: NOT a "still waiting" code — 1032 is "request cancelled by the user", and treating it as
#: pending would leave every cancelled payment polled forever and never marked failed.
#: While the customer still has the PIN prompt open, an stkpushquery does not return a
#: ResultCode at all: it raises (500.001.1001, "transaction is being processed"), which the
#: reconcile task recognises. So "pending" here means only: the gateway gave us no verdict.
CANCELLED_BY_USER = "1032"


def _receipt_from(items) -> str:
    for item in items or []:
        if item.get("Name") == "MpesaReceiptNumber":
            return str(item.get("Value", ""))
    return ""


def _amount_from(items) -> Decimal | None:
    for item in items or []:
        if item.get("Name") == "Amount":
            try:
                return Decimal(str(item.get("Value")))
            except (TypeError, ArithmeticError):
                return None
    return None


class _DarajaGateway(PaymentGateway):
    """Shared behaviour. Subclasses only decide WHOSE credentials to use."""

    def _client(self) -> DarajaClient:
        raise NotImplementedError

    def _callback_path(self) -> str:
        """Where Safaricom should POST the result.

        Per-ISP, and secret: the token both NAMES the operator (so we know whose sale this
        is without trusting anything in the body) and authenticates the call (so a random
        POST is a 404, not a free session).
        """
        return f"/api/v1/payments/hooks/{self.id}/{self.operator.webhook_token}/"

    def charge(self, tx) -> ChargeResult:
        try:
            resp = self._client().stk_push(
                phone=tx.phone,
                amount=int(tx.amount),
                account_reference=tx.account_reference,
                description=tx.plan.name if tx.plan_id else "WiFi",
                callback_path=self._callback_path(),
            )
        except DarajaError as exc:
            raise GatewayError(str(exc)) from exc

        return ChargeResult(
            reference=resp.get("CheckoutRequestID", ""),
            instructions="Enter your M-Pesa PIN on your phone to pay.",
            raw=resp,
        )

    def parse_webhook(self, payload: dict) -> PaymentEvent | None:
        stk = (payload or {}).get("Body", {}).get("stkCallback", {})
        reference = stk.get("CheckoutRequestID", "")
        if not reference:
            return None
        items = (stk.get("CallbackMetadata") or {}).get("Item")
        code = str(stk.get("ResultCode", ""))
        return PaymentEvent(
            reference=reference,
            paid=code == "0",
            receipt=_receipt_from(items),
            amount=_amount_from(items),
            description=str(stk.get("ResultDesc", ""))[:255],
            raw=payload,
        )

    def verify(self, tx) -> PaymentEvent | None:
        """The safety net. Daraja drops callbacks; without this a paid customer sits on a
        spinner forever, which is the bug that cost us a weekend."""
        if not tx.checkout_request_id:
            return None
        try:
            data = self._client().stk_query(tx.checkout_request_id)
        except DarajaError as exc:
            logger.info("verify(%s) not resolvable yet: %s", tx.pk, exc)
            return None

        code = str(data.get("ResultCode", ""))
        if not code:
            # No verdict at all. Say nothing rather than guess — guessing "failed" here
            # would kill a payment the customer is still in the middle of making.
            return PaymentEvent(
                reference=tx.checkout_request_id, paid=False, pending=True, raw=data
            )
        return PaymentEvent(
            reference=tx.checkout_request_id,
            paid=code == "0",
            # A query does NOT return the receipt number. The money is in; the reference
            # is not. Saying so beats inventing one.
            receipt="",
            description=str(data.get("ResultDesc", ""))[:255],
            raw=data,
        )


class WifiosPaybill(_DarajaGateway):
    """Danamo's own paybill: the aggregator. Money lands with US."""

    id = "wifios"
    settlement = PLATFORM

    def _client(self) -> DarajaClient:
        return DarajaClient.for_platform()

    def _callback_path(self) -> str:
        # The platform paybill has ONE callback, shared by every tenant — the transaction
        # is matched on CheckoutRequestID, and the tenant comes from the transaction. Kept
        # on the original URL so shortcodes already registered with Safaricom keep working.
        return f"/api/v1/payments/callback/{settings.DARAJA_CALLBACK_TOKEN}/"


class MpesaDaraja(_DarajaGateway):
    """The ISP's OWN paybill or till. Money lands with THEM, instantly."""

    id = "mpesa"
    settlement = DIRECT

    def _client(self) -> DarajaClient:
        c = self.credentials
        missing = [
            k for k in ("shortcode", "consumer_key", "consumer_secret", "passkey")
            if not c.get(k)
        ]
        if missing:
            raise GatewayError(f"M-Pesa is not fully configured: {', '.join(missing)}.")
        return DarajaClient(
            consumer_key=c["consumer_key"],
            consumer_secret=c["consumer_secret"],
            shortcode=c["shortcode"],
            passkey=c["passkey"],
            collection_method=c.get("collection_method", "paybill"),
        )
