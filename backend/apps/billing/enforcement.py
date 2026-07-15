"""The auto-suspension ladder — derived, never stored.

The whole design turns on one idea: the level an ISP is at is a PURE FUNCTION of what they
owe versus their credit limit. Nothing is stored, so auto-restore is free — the moment a
top-up lands, `amount_owed` drops, the level falls, and every restriction lifts with no
code to unwind. The only stored state is a "we warned you" timestamp, so we nag once per
fall rather than every hour.

The line we do not cross with automation: even at `LOCKED`, we never cut off a subscriber
who has already paid. The ladder stops new sales and paywalls the OWNER's console. Cutting
live service is a manual Danamo decision (a person, an audit line), because on a direct
sale the customer paid the ISP, not us, and is not party to our dispute.
"""

from decimal import Decimal

from apps.billing.services import amount_owed

# --- the credit limit -------------------------------------------------------------------

#: Nobody is enforced below this, however tiny their fees — a floor so a brand-new ISP with
#: almost no history is not tripped by a few shillings.
CREDIT_FLOOR = Decimal("2000.00")
#: Above the floor, the limit scales with what they actually cost us: 1.5x a normal month's
#: fees. A big PPPoE ISP gets more rope than a one-router hotspot, in proportion.
CREDIT_MULTIPLIER = Decimal("1.5")

# --- the ladder (fractions of the limit) ------------------------------------------------

WARN_AT = Decimal("0.6")
RESTRICT_AT = Decimal("1.0")
LOCK_AT = Decimal("1.5")

CURRENT = "current"
WARNED = "warned"
RESTRICTED = "restricted"
LOCKED = "locked"


def expected_monthly_fees(operator) -> Decimal:
    """This ISP's normal monthly bill — their RUN-RATE, from configuration, not history.

    Deliberately NOT the trailing ledger total: an unpaid month IS a trailing fee, so
    basing the limit on ledger history would let a growing debt inflate its own limit and
    never trip enforcement. The run-rate is stable — base subscription plus the per-user
    fee on the clients they are actually serving — so it scales with the ISP's size without
    moving when they fall behind.

    Hotspot commission is left out on purpose: it is small per sale and too variable to
    anchor a credit limit on.
    """
    from apps.pppoe.models import Client

    from .pricing import pppoe_user_fee_total

    base = Decimal(operator.effective_base_fee)
    active = Client.objects.filter(
        operator=operator, status__in=Client.BILLABLE_STATUSES
    ).count()
    pppoe = pppoe_user_fee_total(active, operator) if active else Decimal("0")
    return base + pppoe


def credit_limit(operator) -> Decimal:
    """How much this ISP may owe before enforcement bites. A Danamo-set override wins;
    otherwise 1.5x their monthly run-rate, floored so a tiny ISP still gets real rope."""
    override = getattr(operator, "credit_limit_override", None)
    if override is not None:
        return Decimal(override)
    scaled = (CREDIT_MULTIPLIER * expected_monthly_fees(operator)).quantize(Decimal("0.01"))
    return max(CREDIT_FLOOR, scaled)


def billing_level(operator) -> str:
    """Where this ISP sits on the ladder, RIGHT NOW. Pure: pay and it drops on the next
    read, no job required.

    Danamo's own WISP is never enforced (it does not owe itself). A tenant still in its
    base-fee trial is capped at WARNED — we tell them what is accruing, but we do not lock
    a business that has not started earning yet.
    """
    if getattr(operator, "is_platform_owned", False):
        return CURRENT

    owed = amount_owed(operator)
    limit = credit_limit(operator)
    if limit <= 0:  # a zero override means "never enforce this tenant"
        return CURRENT

    level = CURRENT
    if owed > LOCK_AT * limit:
        level = LOCKED
    elif owed > RESTRICT_AT * limit:
        level = RESTRICTED
    elif owed > WARN_AT * limit:
        level = WARNED

    if level in (RESTRICTED, LOCKED) and _in_trial(operator):
        return WARNED  # leniency during the trial: never cut them off yet
    return level


def can_sell(operator) -> bool:
    """May this ISP take NEW money — an STK push, a fresh voucher? False once restricted.
    Sessions a customer ALREADY paid for are untouched; this only stops new debt piling up
    while they owe."""
    return billing_level(operator) not in (RESTRICTED, LOCKED)


def is_locked(operator) -> bool:
    """Is the OWNER's console down to read-only + pay?"""
    return billing_level(operator) == LOCKED


def owed_summary(operator) -> dict:
    """Everything the console banner and the platform view need, in one call."""
    owed = amount_owed(operator)
    limit = credit_limit(operator)
    return {
        "owed": str(owed),
        "credit_limit": str(limit),
        "level": billing_level(operator),
        "restrict_at": str((RESTRICT_AT * limit).quantize(Decimal("0.01"))),
        "lock_at": str((LOCK_AT * limit).quantize(Decimal("0.01"))),
    }


def _in_trial(operator) -> bool:
    try:
        return operator.in_base_fee_trial()
    except Exception:
        return False
