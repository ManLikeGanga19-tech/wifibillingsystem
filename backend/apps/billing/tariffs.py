"""Estimated M-Pesa / bank transaction costs.

M-Pesa callbacks do NOT return the business fee, so we estimate it from the
published tariff to see true margin. The estimate is corrected against the real
M-Pesa / I&M statement in a monthly true-up. All rates are overridable via
settings so they can be tuned without a code change.

Danamo (the platform) bears these costs — they are NOT charged to ISP wallets.
The platform fees (base + commission + per-user) are priced to cover them.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings


def _d(value) -> Decimal:
    return Decimal(str(value))


def _cfg(name, default):
    return _d(getattr(settings, name, default))


def collection_cost(amount) -> Decimal:
    """Cost to COLLECT a customer payment (C2B paybill / STK). Default tariff:
    percentage of amount, capped, free under a floor (Safaricom till model)."""
    amount = _d(amount)
    free_under = _cfg("MPESA_COLLECT_FREE_UNDER", "200")
    if amount <= free_under:
        return Decimal("0.00")
    pct = _cfg("MPESA_COLLECT_PCT", "0.55") / Decimal("100")
    cap = _cfg("MPESA_COLLECT_CAP", "200")
    cost = (amount * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return min(cost, cap)


def payout_cost(amount, method: str) -> Decimal:
    """Cost to PAY OUT to an ISP. Bank (I&M EFT/Pesalink) is cheap/flat; M-Pesa
    B2C is banded — we use a simple flat estimate per band."""
    amount = _d(amount)
    if method == "bank":
        return _cfg("BANK_PAYOUT_COST", "0")
    # M-Pesa B2C simple band estimate
    for threshold, cost in _b2c_bands():
        if amount <= threshold:
            return cost
    return _cfg("MPESA_B2C_COST_MAX", "60")


def _b2c_bands():
    # (upper amount, estimated cost). Override via settings.MPESA_B2C_BANDS if set.
    bands = getattr(settings, "MPESA_B2C_BANDS", None)
    if bands:
        return [(_d(a), _d(c)) for a, c in bands]
    return [
        (Decimal("1000"), Decimal("20")),
        (Decimal("5000"), Decimal("35")),
        (Decimal("20000"), Decimal("50")),
    ]
