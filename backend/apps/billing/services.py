"""Wallet operations. Every function here is money-critical: atomic, idempotent,
and audited."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.services import audit

from .models import LedgerEntry, Payout

MINIMUM_PAYOUT = Decimal("100.00")


class WalletError(Exception):
    pass


def wallet_balance(operator) -> Decimal:
    return LedgerEntry.objects.filter(operator=operator).aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal("0.00")


def credit_sale(tx) -> None:
    """Credit the ISP's wallet for a successful transaction, withholding the
    platform commission at source. Idempotent per transaction (DB constraint)."""
    operator = tx.operator
    gross = Decimal(tx.amount)
    # str() first: unsaved instances may carry the field default as a float
    rate = Decimal(str(operator.hotspot_commission_pct))
    commission = (gross * rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    try:
        with db_transaction.atomic():
            LedgerEntry.objects.create(
                operator=operator,
                entry_type=LedgerEntry.Type.SALE,
                amount=gross,
                transaction=tx,
                memo=f"Sale {tx.mpesa_receipt or tx.checkout_request_id}",
            )
            if commission > 0:
                LedgerEntry.objects.create(
                    operator=operator,
                    entry_type=LedgerEntry.Type.COMMISSION,
                    amount=-commission,
                    transaction=tx,
                    memo=f"{operator.hotspot_commission_pct}% platform commission",
                )
    except IntegrityError:
        return  # replayed callback — already credited
    audit(
        "wallet_sale_credited",
        operator=operator,
        target=tx,
        gross=str(gross),
        commission=str(commission),
    )


def request_payout(*, operator, amount: Decimal, phone: str, user) -> Payout:
    """Funds are debited (held) immediately so concurrent requests can't
    double-spend the balance."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount < MINIMUM_PAYOUT:
        raise WalletError(f"Minimum withdrawal is KSh {MINIMUM_PAYOUT}.")
    with db_transaction.atomic():
        # Row-level lock on the operator serializes concurrent withdrawals
        op_locked = type(operator).objects.select_for_update().get(pk=operator.pk)
        if amount > wallet_balance(op_locked):
            raise WalletError("Withdrawal exceeds your wallet balance.")
        payout = Payout.objects.create(
            operator=op_locked, amount=amount, phone=phone, requested_by=user
        )
        LedgerEntry.objects.create(
            operator=op_locked,
            entry_type=LedgerEntry.Type.PAYOUT,
            amount=-amount,
            payout=payout,
            memo=f"Withdrawal to {phone}",
        )
    audit("payout_requested", operator=operator, actor=user, target=payout, amount=str(amount))
    return payout


def mark_payout_paid(payout: Payout, *, by, mpesa_reference: str) -> Payout:
    if payout.status != Payout.Status.REQUESTED:
        raise WalletError(f"Payout is already {payout.status}.")
    payout.status = Payout.Status.PAID
    payout.processed_by = by
    payout.processed_at = timezone.now()
    payout.mpesa_reference = mpesa_reference
    payout.save(
        update_fields=["status", "processed_by", "processed_at", "mpesa_reference", "updated_at"]
    )
    audit("payout_paid", operator=payout.operator, actor=by, target=payout, ref=mpesa_reference)
    return payout


def reject_payout(payout: Payout, *, by, note: str) -> Payout:
    """Rejecting returns the held funds to the wallet."""
    if payout.status != Payout.Status.REQUESTED:
        raise WalletError(f"Payout is already {payout.status}.")
    with db_transaction.atomic():
        payout.status = Payout.Status.REJECTED
        payout.processed_by = by
        payout.processed_at = timezone.now()
        payout.note = note
        payout.save(update_fields=["status", "processed_by", "processed_at", "note", "updated_at"])
        LedgerEntry.objects.create(
            operator=payout.operator,
            entry_type=LedgerEntry.Type.ADJUSTMENT,
            amount=payout.amount,
            payout=payout,
            memo=f"Payout rejected: {note}"[:200],
        )
    audit("payout_rejected", operator=payout.operator, actor=by, target=payout, note=note)
    return payout


def charge_monthly_base_fees() -> int:
    """Beat task body (1st of month): deduct each active tenant's base fee.
    Idempotent per (operator, month) via DB constraint."""
    from apps.core.models import Operator

    period = timezone.localdate().strftime("%Y-%m")
    charged = 0
    operators = list(Operator.objects.filter(status=Operator.Status.ACTIVE, base_fee__gt=0))
    for operator in operators:
        try:
            # Savepoint per charge: a duplicate-month conflict must not poison
            # the surrounding transaction
            with db_transaction.atomic():
                LedgerEntry.objects.create(
                    operator=operator,
                    entry_type=LedgerEntry.Type.BASE_FEE,
                    amount=-operator.base_fee,
                    period=period,
                    memo=f"Platform subscription {period}",
                )
            charged += 1
        except IntegrityError:
            continue  # this month already charged
    return charged
