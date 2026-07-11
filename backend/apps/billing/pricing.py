"""Platform revenue pricing — what Danamo charges an ISP for PPPoE users.

The per-user fee is GRADUATED (like tax brackets), so a growing ISP always pays
less per user at the margin and its total bill never falls as it adds users. This
is the large-ISP-friendly rate: the more clients an ISP runs, the better their
blended rate. Tiers are settings-overridable so pricing can change without code.

An Operator may carry a custom flat rate (pppoe_user_fee > 0) negotiated
individually; that overrides the tier table for that tenant.
"""

from decimal import Decimal

from django.conf import settings

# (upper_bound_inclusive | None for unbounded, KSh per user in that bracket)
#
# DEFAULT: graduated 40 / 35 / 30.
#
# Rationale: Danamo ABSORBS the M-Pesa collection cost, so gross != net — a small
# move in this rate has outsized leverage on true margin. Small/mid ISPs (where
# most tenants sit, and who are least price-sensitive) pay 40/35; large ISPs blend
# down toward 30. A 5,000-user ISP blends to ~KES 32.50/user — exactly Centipid's
# $0.25 — so the big accounts we court get the market rate, and the falling rate
# doubles as a growth incentive.
#
# All-in we can still undercut Centipid: their ISP pays them ~32.5 AND pays
# Safaricom's collection fees itself; ours pays one number with fees absorbed.
#
# PROVISIONAL on the high end: if the real Paybill C2B tariff turns out to be
# CUSTOMER-paid (collection costs us ~0), we have room to cut these deliberately.
DEFAULT_PPPOE_TIERS = [
    (500, "40"),
    (2000, "35"),
    (None, "30"),
]


def _tiers():
    raw = getattr(settings, "PPPOE_USER_FEE_TIERS", None) or DEFAULT_PPPOE_TIERS
    return [(None if b is None else int(b), Decimal(str(r))) for b, r in raw]


def pppoe_user_fee_total(count: int, operator=None) -> Decimal:
    """Monthly platform fee for `count` active PPPoE users.

    Graduated across the tier table, unless the operator has a custom flat rate.
    Example (default tiers) for 5,000 users:
        500 x 50 + 1,500 x 40 + 3,000 x 30 = 175,000.
    """
    count = max(int(count), 0)
    if count == 0:
        return Decimal("0.00")

    if operator is not None and operator.pppoe_user_fee:
        flat = Decimal(str(operator.pppoe_user_fee))
        return (flat * count).quantize(Decimal("0.01"))

    total = Decimal("0")
    lower = 0  # users already priced in lower brackets
    for bound, rate in _tiers():
        if lower >= count:
            break
        top = count if bound is None else min(bound, count)
        total += rate * (top - lower)
        lower = top
    return total.quantize(Decimal("0.01"))


def pppoe_blended_rate(count: int, operator=None) -> Decimal:
    """Average KSh/user at this scale — handy for the UI and quotes."""
    count = max(int(count), 0)
    if count == 0:
        return Decimal("0.00")
    return (pppoe_user_fee_total(count, operator) / count).quantize(Decimal("0.01"))
