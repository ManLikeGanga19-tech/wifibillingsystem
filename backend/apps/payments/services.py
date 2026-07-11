"""Payment business logic. The callback handler is the money-critical code path:
it must be idempotent on CheckoutRequestID and must never lose a paid transaction."""

import logging

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.accounts.models import Subscriber
from apps.core.phone import normalize_msisdn
from apps.core.services import audit

from .daraja import DarajaClient
from .models import Transaction

logger = logging.getLogger(__name__)


def initiate_stk_push(*, phone: str, plan, mac: str = "", router=None) -> Transaction:
    """Tenant context comes from the plan: money always flows to the paybill of
    the operator who owns the plan being bought."""
    phone = normalize_msisdn(phone)
    operator = plan.operator
    subscriber, _ = Subscriber.get_or_create_for(operator, phone)
    tx = Transaction.objects.create(
        operator=operator,
        subscriber=subscriber,
        plan=plan,
        router=router,
        phone=phone,
        amount=plan.price,
        mac_address=mac or "",
        # Tenant tag on Danamo's paybill statement (AccountReference max 12 chars)
        account_reference=operator.slug[:12].upper(),
    )
    try:
        resp = DarajaClient(operator).stk_push(
            phone=phone,
            amount=int(plan.price),
            account_reference=tx.account_reference,
            description=plan.name,
        )
    except Exception:
        tx.status = Transaction.Status.FAILED
        tx.result_desc = "STK push initiation failed"
        tx.save(update_fields=["status", "result_desc", "updated_at"])
        raise
    tx.checkout_request_id = resp.get("CheckoutRequestID")
    tx.merchant_request_id = resp.get("MerchantRequestID", "")
    tx.save(update_fields=["checkout_request_id", "merchant_request_id", "updated_at"])
    audit("stk_push_initiated", operator=operator, target=tx, phone=phone, plan=plan.name)
    return tx


def _parse_callback_metadata(stk_callback: dict) -> dict:
    items = (stk_callback.get("CallbackMetadata") or {}).get("Item") or []
    return {item.get("Name"): item.get("Value") for item in items}


def process_stk_callback(payload: dict) -> Transaction | None:
    """Idempotent on CheckoutRequestID. Safe to call any number of times with the
    same payload — only the first call on a pending transaction has effects."""
    stk = (payload.get("Body") or {}).get("stkCallback") or {}
    checkout_id = stk.get("CheckoutRequestID")
    if not checkout_id:
        logger.warning("Callback without CheckoutRequestID: %s", payload)
        return None

    with db_transaction.atomic():
        tx = (
            Transaction.objects.select_for_update()
            .filter(checkout_request_id=checkout_id)
            .first()
        )
        if tx is None:
            logger.warning("Callback for unknown CheckoutRequestID %s", checkout_id)
            return None
        if tx.is_terminal:
            logger.info("Duplicate callback for %s ignored (status=%s)", checkout_id, tx.status)
            return tx

        # Store the raw payload verbatim BEFORE interpreting anything
        tx.raw_callback = payload
        tx.callback_received_at = timezone.now()
        tx.result_code = int(stk.get("ResultCode", -1))
        tx.result_desc = str(stk.get("ResultDesc", ""))[:255]

        if tx.result_code == 0:
            from apps.billing.tariffs import collection_cost

            meta = _parse_callback_metadata(stk)
            tx.mpesa_receipt = str(meta.get("MpesaReceiptNumber", ""))[:30]
            tx.status = Transaction.Status.SUCCESS
            tx.platform_cost = collection_cost(tx.amount)
        else:
            # 1032 = cancelled by user, 1037 = timeout, etc.
            tx.status = (
                Transaction.Status.TIMEOUT
                if tx.result_code == 1037
                else Transaction.Status.FAILED
            )
        tx.save()
        audit(
            "mpesa_callback",
            operator=tx.operator,
            target=tx,
            result_code=tx.result_code,
            status=tx.status,
        )

        if tx.status == Transaction.Status.SUCCESS:
            from apps.billing.services import credit_sale
            from apps.provisioning.tasks import provision_transaction

            credit_sale(tx)
            db_transaction.on_commit(lambda: provision_transaction.delay(tx.id))
    return tx


def mark_reconciled_success(tx: Transaction, query_response: dict) -> None:
    """A pending transaction confirmed paid via STK Query (callback was lost)."""
    with db_transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)
        if tx.is_terminal:
            return
        tx.status = Transaction.Status.RECONCILED
        tx.result_code = 0
        tx.result_desc = "Confirmed via stkpushquery (callback lost)"
        tx.raw_callback = query_response
        tx.callback_received_at = timezone.now()
        tx.save()
        audit("mpesa_reconciled", operator=tx.operator, target=tx)

        from apps.billing.services import credit_sale
        from apps.provisioning.tasks import provision_transaction

        credit_sale(tx)
        db_transaction.on_commit(lambda: provision_transaction.delay(tx.id))
