"""Monthly platform statements — the ISP's formal record of what we charged them.

A statement, not a fresh charge: the fees were already accrued as they happened, and
enforcement already runs on the live balance. This snapshots a month so every fee is on a
document the ISP can file — direct-sale commission as money DUE, aggregator commission as
already-deducted, nothing missing.

Settlement tracks the RUNNING account, not per-invoice cash: when a top-up brings the
platform balance back to zero-or-above, the ISP is square with us, so every outstanding
statement is marked paid. A partial payment leaves them outstanding — you are either clear
with us or you are not.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.services import audit

from .models import LedgerEntry, PlatformInvoice, PlatformLedgerEntry

logger = logging.getLogger(__name__)


def _period_bounds(period: str):
    """[start, end) datetimes for a YYYY-MM period, in the project timezone."""
    from datetime import datetime

    year, month = int(period[:4]), int(period[5:7])
    start = timezone.make_aware(datetime(year, month, 1))
    end = (
        timezone.make_aware(datetime(year + 1, 1, 1))
        if month == 12
        else timezone.make_aware(datetime(year, month + 1, 1))
    )
    return start, end


def _prior_period(today=None) -> str:
    today = today or timezone.localdate()
    year, month = today.year, today.month
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def build_invoice(operator, period: str) -> PlatformInvoice | None:
    """Snapshot one operator's fees for one month. Idempotent per (operator, period):
    a re-run returns the existing statement rather than a duplicate. Returns None if the
    month had no fees at all (nothing to state)."""
    start, end = _period_bounds(period)

    def platform_sum(reason) -> Decimal:
        v = PlatformLedgerEntry.objects.filter(
            operator=operator, reason=reason, created_at__gte=start, created_at__lt=end
        ).aggregate(v=Sum("amount"))["v"]
        return -(v or Decimal("0.00"))  # fees are stored negative; state them positive

    base = platform_sum(PlatformLedgerEntry.Reason.BASE_FEE)
    pppoe = platform_sum(PlatformLedgerEntry.Reason.PPPOE_FEE)
    setup = platform_sum(PlatformLedgerEntry.Reason.SETUP_FEE)
    direct_comm = platform_sum(PlatformLedgerEntry.Reason.COMMISSION)
    sms = platform_sum(PlatformLedgerEntry.Reason.SMS)

    # Aggregator commission, withheld at source in the wallet — informational only.
    withheld = -(
        LedgerEntry.objects.filter(
            operator=operator,
            entry_type=LedgerEntry.Type.COMMISSION,
            created_at__gte=start,
            created_at__lt=end,
        ).aggregate(v=Sum("amount"))["v"]
        or Decimal("0.00")
    )

    total = base + pppoe + setup + direct_comm + sms
    if total == 0 and withheld == 0:
        return None  # a month with no activity gets no statement

    try:
        with db_transaction.atomic():
            invoice = PlatformInvoice.objects.create(
                operator=operator,
                period=period,
                base_fee=base,
                pppoe_fee=pppoe,
                setup_fee=setup,
                direct_commission=direct_comm,
                sms=sms,
                withheld_commission=withheld,
                total=total,
            )
    except IntegrityError:
        return PlatformInvoice.objects.get(operator=operator, period=period)

    audit("platform_invoice_issued", operator=operator, target=invoice,
          period=period, total=str(total))
    return invoice


def issue_monthly_invoices(period: str = "") -> int:
    """Beat body (1st of the month): a statement per operator for the prior month."""
    from apps.core.models import Operator

    period = period or _prior_period()
    issued = 0
    for operator in Operator.objects.filter(is_platform_owned=False):
        if build_invoice(operator, period) is not None:
            issued += 1
    return issued


def settle_outstanding_if_clear(operator) -> int:
    """Called after a top-up credits the account. If the ISP is now square with us
    (balance >= 0), mark every outstanding statement paid. Returns how many.

    Deliberately all-or-nothing: the platform account is one running balance, so 'paid' can
    only honestly mean 'you owe us nothing right now'. A partial payment leaves the
    statements outstanding, which is the truth.
    """
    from .platform_account import balance

    if balance(operator) < 0:
        return 0
    now = timezone.now()
    updated = PlatformInvoice.objects.filter(
        operator=operator, status=PlatformInvoice.Status.OUTSTANDING
    ).update(status=PlatformInvoice.Status.PAID, paid_at=now)
    if updated:
        audit("platform_invoices_settled", operator=operator, count=updated)
    return updated
