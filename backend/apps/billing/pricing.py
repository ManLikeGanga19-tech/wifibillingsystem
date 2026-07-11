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
# DEFAULT: a single flat rate that MATCHES Centipid's ~$0.25 (~KES 32.5) per
# user. PROVISIONAL — confirm this still profits once the real Paybill C2B
# collection tariff (which the platform absorbs) is known; nudge up if margin on
# high-value packages is thin. The graduated multi-tier form below is retained
# for custom large-ISP deals (set PPPOE_USER_FEE_TIERS in settings).
DEFAULT_PPPOE_TIERS = [
    (None, "30"),
]

# A ready-made graduated table for large-ISP negotiations (not the default):
GRADUATED_PPPOE_TIERS = [
    (500, "50"),
    (2000, "40"),
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
