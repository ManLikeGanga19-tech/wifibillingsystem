"""SMS credits: what an ISP spends when they send on the managed WIFI.OS gateway.

Two rules hold this together:

  * The balance is the SUM of the ledger, never a stored counter. A counter that got
    decremented twice on a Celery retry would quietly rob an ISP of SMS they paid for,
    and no one could prove it afterwards.
  * A purchase is money, so it moves through the SAME wallet ledger as everything else
    (a negative billing.LedgerEntry), inside one transaction with the credit grant. There
    is no second money rail to reconcile, and the wallet always explains itself.

Bundles are priced with a volume discount: buying more lowers the per-SMS cost, which is
how every SMS reseller in the market prices and what an ISP will compare us against.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Sum

from apps.billing.models import LedgerEntry
from apps.billing.services import WalletError, wallet_balance
from apps.core.services import audit

from .models import SmsCreditEntry


@dataclass(frozen=True)
class Bundle:
    id: str
    credits: int
    price: Decimal

    @property
    def per_sms(self) -> Decimal:
        return (self.price / self.credits).quantize(Decimal("0.01"))


BUNDLES: list[Bundle] = [
    Bundle("starter", 1_000, Decimal("800.00")),  # 0.80/SMS
    Bundle("growth", 5_000, Decimal("3750.00")),  # 0.75/SMS
    Bundle("scale", 20_000, Decimal("14000.00")),  # 0.70/SMS
    Bundle("bulk", 100_000, Decimal("65000.00")),  # 0.65/SMS
]

#: Warn the ISP here — enough runway to top up before customers stop getting receipts.
LOW_BALANCE = 200

#: What a new ISP is given so their very first sale still sends a receipt. The managed
#: gateway promises "it works on day one"; a zero balance would make that a lie. Small
#: enough that a real business tops up within their first weeks. Granted in signals.py.
WELCOME_CREDITS = 250


def bundle(bundle_id: str) -> Bundle | None:
    return next((b for b in BUNDLES if b.id == bundle_id), None)


def balance(operator) -> int:
    return (
        SmsCreditEntry.objects.filter(operator=operator).aggregate(v=Sum("credits"))["v"] or 0
    )


@db_transaction.atomic
def purchase(*, operator, bundle_id: str, user) -> SmsCreditEntry:
    """Buy credits with wallet money. Atomic: the ISP is never debited without receiving
    credits, and never receives credits without being debited."""
    chosen = bundle(bundle_id)
    if chosen is None:
        raise WalletError("That bundle does not exist.")

    available = wallet_balance(operator)
    if available < chosen.price:
        raise WalletError(
            f"Your wallet has KSh {available:,.2f}. This bundle costs "
            f"KSh {chosen.price:,.2f} — take less out at your next payout, or wait for "
            "today's sales to land."
        )

    LedgerEntry.objects.create(
        operator=operator,
        entry_type=LedgerEntry.Type.SMS_CREDITS,
        amount=-chosen.price,
        memo=f"{chosen.credits:,} SMS credits",
    )
    entry = SmsCreditEntry.objects.create(
        operator=operator,
        credits=chosen.credits,
        reason=SmsCreditEntry.Reason.PURCHASE,
        amount=chosen.price,
        memo=f"{chosen.credits:,} SMS bundle",
    )
    audit(
        "sms_credits_bought",
        operator=operator,
        actor=user,
        target=operator,
        credits=chosen.credits,
        amount=str(chosen.price),
    )
    return entry


def consume(operator, message, segments: int = 1) -> None:
    """Debit credits for one sent message.

    Idempotent by construction: SmsCreditEntry has a unique constraint on `message`, so a
    retried Celery task cannot double-charge. We swallow the collision rather than raise —
    the message DID go out, and failing the task here would only send it twice.
    """
    from django.db import IntegrityError

    try:
        with db_transaction.atomic():
            SmsCreditEntry.objects.create(
                operator=operator,
                credits=-abs(segments),
                reason=SmsCreditEntry.Reason.SEND,
                message=message,
            )
    except IntegrityError:
        pass  # already debited for this message


def has_credit(operator) -> bool:
    return balance(operator) > 0
