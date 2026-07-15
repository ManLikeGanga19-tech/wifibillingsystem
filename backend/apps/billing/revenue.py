"""Platform revenue — the fees an ISP pays US, wherever they now sit.

After the finance refactor a fee lives in one of two places, and this module is the single
seam that spans both so no revenue is ever miscounted:

  * AGGREGATOR commission is WITHHELD at source — a negative COMMISSION entry in the wallet
    (billing.LedgerEntry). We hold the cash; the debit is our margin.
  * Everything else (direct-sale commission, base fee, PPPoE fee, setup fee) is ACCRUED as
    a debt on the platform account (billing.PlatformLedgerEntry). The ISP owes it; it is
    still our revenue.

Every caller that asks "what did the platform earn?" goes through here, so moving a fee
between ledgers can never silently drop it from the books.
"""

from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from .models import LedgerEntry, PlatformLedgerEntry

_MONEY = DecimalField(max_digits=14, decimal_places=2)

#: Platform-account reasons that are revenue to us (not top-ups, grants or refunds).
PLATFORM_REVENUE_REASONS = [
    PlatformLedgerEntry.Reason.COMMISSION,
    PlatformLedgerEntry.Reason.BASE_FEE,
    PlatformLedgerEntry.Reason.PPPOE_FEE,
    PlatformLedgerEntry.Reason.SETUP_FEE,
]
#: The recurring subset — what MRR means (a one-off setup fee is not recurring).
RECURRING_REASONS = [
    PlatformLedgerEntry.Reason.COMMISSION,
    PlatformLedgerEntry.Reason.BASE_FEE,
    PlatformLedgerEntry.Reason.PPPOE_FEE,
]


def _sum(qs, field="amount") -> Decimal:
    return qs.aggregate(v=Coalesce(Sum(field), Value(Decimal("0")), output_field=_MONEY))["v"]


def platform_earnings(*, start=None, end=None, operator=None, recurring_only=False) -> Decimal:
    """Total fees the platform earned, POSITIVE, across both ledgers.

    Fees are stored as negative debits (they reduce what the ISP has), so we negate to get
    revenue. `start`/`end` filter on created_at; `operator` scopes to one tenant.
    """
    reasons = RECURRING_REASONS if recurring_only else PLATFORM_REVENUE_REASONS

    # Platform-account fees (direct commission, base, pppoe, setup).
    plat = PlatformLedgerEntry.objects.filter(reason__in=reasons)
    # Aggregator commission, withheld in the wallet.
    wallet = LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION)

    if operator is not None:
        plat = plat.filter(operator=operator)
        wallet = wallet.filter(operator=operator)
    if start is not None:
        plat = plat.filter(created_at__gte=start)
        wallet = wallet.filter(created_at__gte=start)
    if end is not None:
        plat = plat.filter(created_at__lt=end)
        wallet = wallet.filter(created_at__lt=end)

    return -(_sum(plat) + _sum(wallet))


def platform_earnings_by_stream(*, start=None, end=None) -> dict[str, Decimal]:
    """Revenue split by kind, for the Command Center. Direct + aggregator commission are
    the same 'commission' stream from the platform's point of view."""
    result: dict[str, Decimal] = {}
    for reason in PLATFORM_REVENUE_REASONS:
        qs = PlatformLedgerEntry.objects.filter(reason=reason)
        if start is not None:
            qs = qs.filter(created_at__gte=start)
        if end is not None:
            qs = qs.filter(created_at__lt=end)
        result[reason] = -_sum(qs)

    # Fold the withheld aggregator commission into the commission stream.
    wallet = LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION)
    if start is not None:
        wallet = wallet.filter(created_at__gte=start)
    if end is not None:
        wallet = wallet.filter(created_at__lt=end)
    result[PlatformLedgerEntry.Reason.COMMISSION] += -_sum(wallet)

    return result
