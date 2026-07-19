"""The ISP's account WITH WIFI.OS — what they owe us, or have prepaid.

Distinct from the wallet, which is money we hold FOR them. An ISP selling through their
own gateway never has a wallet balance at all, yet still owes us for SMS and for the
commission on every direct sale. That debt lives here.

Denominated in shillings, signed, and the balance is the SUM of the ledger — never a
stored counter. A counter decremented twice on a Celery retry silently robs an ISP of
money they paid, and nobody can prove it afterwards.

A NEGATIVE balance is normal: this is postpaid. Fees accrue as they happen; the ISP
settles by STK push.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Sum

from apps.core.services import audit

from .models import PlatformLedgerEntry

# --- pricing ---------------------------------------------------------------------------

#: What one SMS segment costs an ISP. A message over 160 characters is several segments,
#: because that is what the gateway charges US for.
SMS_PRICE = Decimal("0.80")

#: What a new ISP is given so their very first sale still sends a receipt. The managed
#: gateway promises "it works on day one"; a zero balance would make that a lie.
WELCOME_CREDIT = Decimal("200.00")  # 250 SMS

#: Warn here — enough runway to top up before receipts start failing.
DEFAULT_LOW_BALANCE = Decimal("200.00")


@dataclass(frozen=True)
class Bundle:
    id: str
    price: Decimal  # what they pay by STK
    credit: Decimal  # what we credit — bigger on the larger bundles

    @property
    def sms(self) -> int:
        return int(self.credit / SMS_PRICE)

    @property
    def per_sms(self) -> Decimal:
        return (self.price / self.sms).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def bonus(self) -> Decimal:
        return self.credit - self.price


#: The volume discount is expressed as BONUS CREDIT rather than a cheaper per-SMS rate,
#: because the balance is in shillings and SMS has one price. Pay for 3,750, get 4,000 —
#: same effect, and the ledger stays honest about what a message actually costs.
BUNDLES: list[Bundle] = [
    Bundle("starter", Decimal("800.00"), Decimal("800.00")),  # 1,000 SMS @ 0.80
    Bundle("growth", Decimal("3750.00"), Decimal("4000.00")),  # 5,000 SMS @ 0.75
    Bundle("scale", Decimal("14000.00"), Decimal("16000.00")),  # 20,000 SMS @ 0.70
    Bundle("bulk", Decimal("65000.00"), Decimal("80000.00")),  # 100,000 SMS @ 0.65
]

MIN_TOPUP = Decimal("50.00")
MAX_TOPUP = Decimal("150000.00")


def bundle(bundle_id: str) -> Bundle | None:
    return next((b for b in BUNDLES if b.id == bundle_id), None)


class PlatformAccountError(Exception):
    pass


# --- balance ----------------------------------------------------------------------------


def balance(operator) -> Decimal:
    return PlatformLedgerEntry.objects.filter(operator=operator).aggregate(
        v=Sum("amount")
    )["v"] or Decimal("0.00")


def debt(operator) -> Decimal:
    """What the platform account says the ISP owes us, BEFORE netting against any wallet
    money we hold for them. A positive number. (A positive balance — prepaid SMS — is not
    debt, so this floors at zero.)"""
    return max(Decimal("0.00"), -balance(operator))


def can_send_sms(operator) -> bool:
    """SMS is prepaid: we pay the gateway the moment it leaves, so a negative balance
    cannot buy more. Fees may drive the balance below zero (that is postpaid, and it is
    invoiced) — but once it is below zero the ISP is spending money they have not given
    us, and SMS stops until they top up."""
    return balance(operator) > 0


def sms_cost(segments: int) -> Decimal:
    return (SMS_PRICE * segments).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- charges -----------------------------------------------------------------------------


def charge_sms(operator, message, segments: int = 1) -> None:
    """Bill one sent message.

    Idempotent by construction: the ledger has a unique constraint on `message`, so a
    retried Celery task cannot bill twice. The collision is swallowed rather than raised —
    the message DID go out, and failing the task here would only send it again.
    """
    try:
        with db_transaction.atomic():
            PlatformLedgerEntry.objects.create(
                operator=operator,
                amount=-sms_cost(segments),
                reason=PlatformLedgerEntry.Reason.SMS,
                message=message,
                memo=f"SMS ({segments} segment{'s' if segments != 1 else ''})",
            )
    except IntegrityError:
        pass  # already charged for this message


def accrue_fee(operator, amount: Decimal, *, reason: str, memo: str = "", period: str = "",
               transaction=None) -> PlatformLedgerEntry | None:
    """Charge a platform FEE to the ISP's account — the debt they settle by STK.

    This is the single door every fee comes through now (base, PPPoE, the commission on a
    DIRECT sale). "Nothing goes unnoticed": every fee, whatever gateway the sale used, lands
    here where the exposure check and the monthly invoice can both see it.

    `period` (YYYY-MM) makes a periodic fee idempotent per month via the ledger's unique
    constraint; a `transaction` link makes a per-sale commission idempotent per sale.
    Returns None if it was a duplicate (already charged).
    """
    amount = Decimal(amount)
    if amount == 0:
        return None
    try:
        with db_transaction.atomic():
            return PlatformLedgerEntry.objects.create(
                operator=operator,
                amount=-abs(amount),  # a fee always debits
                reason=reason,
                period=period,
                transaction=transaction,
                memo=memo,
            )
    except IntegrityError:
        return None  # this month / this sale already charged


def grant(operator, amount: Decimal, *, memo: str = "") -> PlatformLedgerEntry:
    return PlatformLedgerEntry.objects.create(
        operator=operator,
        amount=Decimal(amount),
        reason=PlatformLedgerEntry.Reason.GRANT,
        memo=memo or "Credit granted",
    )


def _topup_memo(topup) -> str:
    bonus = Decimal(topup.credit) - Decimal(topup.amount)
    if bonus > 0:
        return f"Top-up {topup.mpesa_receipt} (+KSh {bonus:,.0f} bonus)"
    return f"Top-up {topup.mpesa_receipt}"


def credit_topup(topup) -> None:
    """Credit a PAID top-up. Idempotent — Safaricom replays callbacks."""
    try:
        with db_transaction.atomic():
            PlatformLedgerEntry.objects.create(
                operator=topup.operator,
                amount=Decimal(topup.credit),
                reason=PlatformLedgerEntry.Reason.TOPUP,
                topup=topup,
                memo=_topup_memo(topup),
            )
    except IntegrityError:
        return  # replayed callback — already credited
    audit(
        "platform_topup_credited",
        operator=topup.operator,
        target=topup,
        amount=str(topup.amount),
        credit=str(topup.credit),
    )
    # If that cleared their debt, their outstanding statements are now paid.
    from .invoicing import settle_outstanding_if_clear

    settle_outstanding_if_clear(topup.operator)


# --- reporting: what the ISP paid US (their auto expense line) ---------------------------

#: The charges that are genuinely the ISP's cost of using WIFI.OS — money to Danamo. Top-ups and
#: grants FUND the account; refunds/adjustments are corrections; none of those are an expense.
FEE_REASONS = (
    PlatformLedgerEntry.Reason.BASE_FEE,
    PlatformLedgerEntry.Reason.COMMISSION,
    PlatformLedgerEntry.Reason.PPPOE_FEE,
    PlatformLedgerEntry.Reason.SETUP_FEE,
    PlatformLedgerEntry.Reason.SMS,
)


def platform_charges(operator, *, start, end) -> dict:
    """What the platform charged this ISP in [start, end) — surfaced on their Expenses page as an
    auto 'WIFI.OS platform fees' line so their profit picture includes what they pay us.

    Charges are stored NEGATIVE (a fee debits), so we flip each to a positive cost. Returns
    {by_reason: {reason: Decimal}, total: Decimal} with every fee reason present (zero if none)."""
    rows = (
        PlatformLedgerEntry.objects.filter(
            operator=operator, reason__in=FEE_REASONS,
            created_at__gte=start, created_at__lt=end,
        )
        .values("reason")
        .annotate(total=Sum("amount"))
    )
    by_reason = {r: Decimal("0.00") for r in FEE_REASONS}
    for row in rows:
        by_reason[row["reason"]] = (-row["total"]).quantize(Decimal("0.01"))
    total = sum(by_reason.values(), Decimal("0.00"))
    return {"by_reason": by_reason, "total": total}
