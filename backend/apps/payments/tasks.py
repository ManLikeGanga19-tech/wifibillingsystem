import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# ResultCodes from stkpushquery that mean "still waiting for the user"
_STILL_PROCESSING_ERRORS = ("500.001.1001",)
MAX_RECONCILE_ATTEMPTS = 5


@shared_task
def reconcile_pending_transactions():
    """Callbacks get lost in the wild. Every 5 minutes, ask Daraja directly about
    transactions still pending after 2 minutes and settle them."""
    from .daraja import DarajaClient, DarajaError
    from .models import Transaction
    from .services import mark_reconciled_success

    cutoff = timezone.now() - timedelta(minutes=2)
    stale = Transaction.objects.filter(
        status=Transaction.Status.PENDING,
        created_at__lt=cutoff,
        created_at__gt=timezone.now() - timedelta(hours=24),
        checkout_request_id__isnull=False,
        reconcile_attempts__lt=MAX_RECONCILE_ATTEMPTS,
    )
    settled = 0
    for tx in stale.iterator():
        try:
            resp = DarajaClient(tx.operator).stk_query(tx.checkout_request_id)
        except DarajaError as exc:
            if any(code in str(exc) for code in _STILL_PROCESSING_ERRORS):
                continue  # user still has the PIN prompt open
            logger.warning("stk_query failed for %s: %s", tx.checkout_request_id, exc)
            tx.reconcile_attempts += 1
            tx.save(update_fields=["reconcile_attempts", "updated_at"])
            continue

        result_code = str(resp.get("ResultCode", ""))
        tx.reconcile_attempts += 1
        if result_code == "0":
            mark_reconciled_success(tx, resp)
            settled += 1
        elif result_code:
            tx.status = (
                Transaction.Status.TIMEOUT
                if result_code == "1037"
                else Transaction.Status.FAILED
            )
            tx.result_code = int(result_code) if result_code.lstrip("-").isdigit() else None
            tx.result_desc = str(resp.get("ResultDesc", ""))[:255]
            tx.save()
            settled += 1
        else:
            tx.save(update_fields=["reconcile_attempts", "updated_at"])
    if settled:
        logger.info("Reconciliation settled %d transactions", settled)
    return settled
