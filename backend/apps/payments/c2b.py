"""C2B (paybill) handling for broadband payments on Danamo's shared shortcode.

The customer types their globally-unique account number as the M-Pesa account
reference (BillRefNumber); that routes the payment to the right ISP + client.
Idempotent on the M-Pesa TransID.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction

from .models import C2BPayment

logger = logging.getLogger(__name__)


def find_client(bill_ref: str):
    from apps.pppoe.models import Client

    return Client.objects.filter(account_number=(bill_ref or "").strip().upper()).first()


def process_c2b_confirmation(payload: dict) -> C2BPayment | None:
    """Safaricom C2B confirmation. Idempotent on TransID; stores raw payload;
    matches the account number to a client and records the payment."""
    trans_id = payload.get("TransID") or payload.get("TransactionID")
    if not trans_id:
        logger.warning("C2B without TransID: %s", payload)
        return None

    existing = C2BPayment.objects.filter(trans_id=trans_id).first()
    if existing:
        return existing  # replayed confirmation — no double credit

    bill_ref = payload.get("BillRefNumber", "")
    amount = Decimal(str(payload.get("TransAmount", "0") or "0"))
    client = find_client(bill_ref)

    from apps.billing.tariffs import collection_cost

    try:
        with db_transaction.atomic():
            payment = C2BPayment.objects.create(
                trans_id=trans_id,
                bill_ref=bill_ref,
                msisdn=str(payload.get("MSISDN", ""))[:15],
                amount=amount,
                first_name=str(payload.get("FirstName", ""))[:60],
                operator=client.operator if client else None,
                client=client,
                status=C2BPayment.Status.MATCHED if client else C2BPayment.Status.UNMATCHED,
                raw_payload=payload,
                platform_cost=collection_cost(amount),
            )
    except IntegrityError:
        # concurrent duplicate confirmation
        return C2BPayment.objects.filter(trans_id=trans_id).first()

    if client:
        from apps.pppoe.services import record_client_payment

        record_client_payment(client, amount, source="c2b", memo=f"M-Pesa {trans_id}")
    else:
        logger.warning("C2B %s: no client for account %r", trans_id, bill_ref)
    return payment
