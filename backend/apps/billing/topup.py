"""An ISP topping up their platform account, by STK push to Danamo's paybill.

This is money flowing the OPPOSITE way to everything else in payments/: the ISP pays US.
It gets its own model, its own callback URL and its own reconciliation for exactly that
reason — landing an ISP's top-up in the subscriber-payment handler would credit them for a
sale no customer ever made.

The hard-won lesson from the hotspot bug is baked in: **a callback that never arrives must
not strand the money.** Safaricom drops them. So every pending top-up is queried back
against Daraja on a timer, and the ledger credit is idempotent, so the callback and the
reconciler racing each other is a no-op rather than a double credit.
"""

import logging
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.services import audit
from apps.payments.daraja import DarajaClient, DarajaError

from . import platform_account
from .models import TopUp

logger = logging.getLogger(__name__)

CALLBACK_PATH_NAME = "topup-callback"

#: Callbacks get lost in the wild. Query anything still pending after this.
RECONCILE_AFTER_SECONDS = 30
MAX_RECONCILE_ATTEMPTS = 8


class TopUpError(Exception):
    pass


def _callback_path() -> str:
    from django.conf import settings

    return f"/api/v1/billing/topup/callback/{settings.DARAJA_CALLBACK_TOKEN}/"


def initiate(*, operator, phone: str, bundle_id: str = "", amount=None, user=None) -> TopUp:
    """Send the ISP an STK prompt for a bundle (or a custom amount)."""
    try:
        msisdn = normalize_msisdn(phone)
    except InvalidPhoneError as exc:
        raise TopUpError(str(exc)) from exc

    if bundle_id:
        chosen = platform_account.bundle(bundle_id)
        if chosen is None:
            raise TopUpError("That bundle does not exist.")
        pay, credit = chosen.price, chosen.credit
    else:
        try:
            pay = Decimal(str(amount)).quantize(Decimal("0.01"))
        except (TypeError, ArithmeticError) as exc:
            raise TopUpError("Enter an amount.") from exc
        if pay < platform_account.MIN_TOPUP:
            raise TopUpError(f"The smallest top-up is KSh {platform_account.MIN_TOPUP:,.0f}.")
        if pay > platform_account.MAX_TOPUP:
            raise TopUpError(f"The largest top-up is KSh {platform_account.MAX_TOPUP:,.0f}.")
        credit = pay  # no bonus on a custom amount — bonuses belong to the bundles

    topup = TopUp.objects.create(
        operator=operator,
        amount=pay,
        credit=credit,
        bundle=bundle_id,
        phone=msisdn,
        checkout_request_id=None,  # filled below; a failed push leaves no orphan row
    )
    try:
        resp = DarajaClient().stk_push(
            phone=msisdn,
            amount=int(pay),  # Daraja takes whole shillings
            account_reference=f"TOPUP{operator.id}",
            description="SMS top-up",
            callback_path=_callback_path(),
        )
    except DarajaError as exc:
        topup.delete()
        raise TopUpError(f"M-Pesa did not accept the request: {exc}") from exc

    topup.checkout_request_id = resp.get("CheckoutRequestID", "")
    topup.merchant_request_id = resp.get("MerchantRequestID", "")
    topup.save(update_fields=["checkout_request_id", "merchant_request_id", "updated_at"])

    audit(
        "platform_topup_started",
        operator=operator,
        actor=user,
        target=topup,
        amount=str(pay),
        credit=str(credit),
    )
    return topup


def _finish(topup: TopUp, *, ok: bool, receipt: str = "", desc: str = "", raw=None) -> None:
    """Land a terminal result. Idempotent: a replayed callback (or the reconciler racing
    the callback) must not credit twice."""
    with db_transaction.atomic():
        locked = TopUp.objects.select_for_update().get(pk=topup.pk)
        if locked.status != TopUp.Status.PENDING:
            return  # already terminal — nothing to do
        locked.raw_callback = raw
        locked.callback_received_at = timezone.now()
        locked.result_desc = (desc or "")[:200]
        if ok:
            locked.status = TopUp.Status.SUCCESS
            locked.mpesa_receipt = receipt
        else:
            locked.status = TopUp.Status.FAILED
        locked.save()

    if ok:
        # Outside the status transaction, but itself idempotent (unique on topup).
        platform_account.credit_topup(locked)


def handle_callback(payload: dict) -> TopUp | None:
    """Daraja STK callback for a top-up. Returns the TopUp, or None if we do not know it."""
    body = (payload or {}).get("Body", {}).get("stkCallback", {})
    checkout_id = body.get("CheckoutRequestID", "")
    if not checkout_id:
        return None

    topup = TopUp.objects.filter(checkout_request_id=checkout_id).first()
    if topup is None:
        logger.warning("top-up callback for unknown CheckoutRequestID %s", checkout_id)
        return None

    result_code = str(body.get("ResultCode", ""))
    desc = body.get("ResultDesc", "")
    receipt = ""
    for item in body.get("CallbackMetadata", {}).get("Item", []):
        if item.get("Name") == "MpesaReceiptNumber":
            receipt = str(item.get("Value", ""))

    _finish(topup, ok=result_code == "0", receipt=receipt, desc=desc, raw=payload)
    return topup


def reconcile(topup: TopUp) -> None:
    """Ask Daraja what actually happened. The safety net for a callback that never came —
    without this, an ISP who paid would sit on a spinner and their SMS would stay off."""
    topup.reconcile_attempts += 1
    topup.save(update_fields=["reconcile_attempts", "updated_at"])
    try:
        data = DarajaClient().stk_query(topup.checkout_request_id)
    except DarajaError as exc:
        logger.info("top-up %s not resolvable yet: %s", topup.pk, exc)
        return

    code = str(data.get("ResultCode", ""))
    if code == "0":
        # Daraja's query does not return the receipt; the money is in, the reference is not.
        _finish(topup, ok=True, desc=data.get("ResultDesc", "Reconciled"), raw=data)
    elif code and code != "1032":  # 1032 = still awaiting the user's PIN
        _finish(topup, ok=False, desc=data.get("ResultDesc", "Failed"), raw=data)
