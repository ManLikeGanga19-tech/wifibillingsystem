import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ResultCodes from stkpushquery that mean "still waiting for the user"
_STILL_PROCESSING_ERRORS = ("500.001.1001",)
MAX_RECONCILE_ATTEMPTS = 8

# How old a pending transaction must be before we ask Daraja about it. THIS IS A
# CUSTOMER-EXPERIENCE NUMBER, not a housekeeping one: a hotspot customer is standing
# there watching a spinner, so the safety net for a lost callback has to fire while
# they are still waiting — not minutes later, after the portal has given up and their
# phone has stopped trying to log in. Kept just above the time it takes to enter a PIN,
# so we rarely query a prompt that is still open (which is cheap anyway — Daraja says
# "still processing" and we retry). Overridable for staging/prod.
RECONCILE_AFTER_SECONDS = getattr(settings, "RECONCILE_AFTER_SECONDS", 25)


@shared_task
def reconcile_pending_transactions():
    """Callbacks get lost in the wild — a dead tunnel in dev, a genuine drop in prod.

    So the callback is the FAST path, and this is the SAFETY NET that must be fast
    enough to matter: it runs every ~20s and settles anything still pending after
    ~25s by asking Daraja directly. That window is deliberately inside the portal's
    polling window, so a lost callback costs the customer seconds, not a failed
    connection."""
    from .daraja import DarajaError
    from .gateways import GatewayError, gateway_for_transaction
    from .models import Transaction
    from .services import mark_reconciled_success

    cutoff = timezone.now() - timedelta(seconds=RECONCILE_AFTER_SECONDS)
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
            # The gateway it was TAKEN on — not whatever the ISP has active now. Querying
            # an ISP's own shortcode for a payment made on ours (or vice versa) would come
            # back "unknown" and we would fail a payment that actually succeeded.
            event = gateway_for_transaction(tx).verify(tx)
        except (DarajaError, GatewayError) as exc:
            if any(code in str(exc) for code in _STILL_PROCESSING_ERRORS):
                continue  # user still has the PIN prompt open
            logger.warning("verify failed for %s: %s", tx.checkout_request_id, exc)
            tx.reconcile_attempts += 1
            tx.save(update_fields=["reconcile_attempts", "updated_at"])
            continue

        if event is None or event.pending:
            continue  # the gateway cannot say yet; try again next sweep

        resp = event.raw
        result_code = "0" if event.paid else str(resp.get("ResultCode", "1"))
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
