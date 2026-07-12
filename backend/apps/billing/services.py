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


def credit_pppoe_payment(operator, amount: Decimal, *, memo: str = "") -> None:
    """Credit the ISP wallet for a broadband (C2B) payment. No commission is
    withheld here — the platform charges a flat per-active-user fee monthly
    instead (charge_pppoe_user_fees)."""
    LedgerEntry.objects.create(
        operator=operator,
        entry_type=LedgerEntry.Type.SALE,
        amount=Decimal(amount),
        memo=memo or "PPPoE payment",
    )
    audit("wallet_pppoe_credited", operator=operator, amount=str(amount))


def charge_pppoe_user_fees() -> int:
    """Beat (monthly): deduct the platform's per-user fee from each tenant's
    wallet, counting ONLY clients actually being served (Client.BILLABLE_STATUSES
    = active). Suspended clients have not paid their ISP and have no internet —
    the ISP is not charged for them. The fee is graduated by user count
    (apps.billing.pricing) unless the tenant has a custom flat rate. Idempotent
    per (operator, month) via the ledger constraint."""
    from apps.core.models import Operator
    from apps.pppoe.models import Client

    from .pricing import pppoe_user_fee_total

    period = timezone.localdate().strftime("%Y-%m")
    charged = 0
    operators = Operator.objects.filter(
        status=Operator.Status.ACTIVE, is_platform_owned=False
    )
    for operator in operators:
        active = Client.objects.filter(
            operator=operator, status__in=Client.BILLABLE_STATUSES
        ).count()
        if active == 0:
            continue
        fee = pppoe_user_fee_total(active, operator)
        if fee <= 0:
            continue
        try:
            with db_transaction.atomic():
                LedgerEntry.objects.create(
                    operator=operator,
                    entry_type=LedgerEntry.Type.PPPOE_FEE,
                    amount=-fee,
                    period=period,
                    memo=f"PPPoE platform fee {period} ({active} users)",
                )
            charged += 1
        except IntegrityError:
            continue  # this month already charged
    return charged


def charge_setup_fee(operator) -> bool:
    """One-time onboarding fee, billed to the ISP wallet when it is approved.
    Idempotent: at most one SETUP_FEE entry per operator, ever. Returns True if
    a charge was made. Recouped from the tenant's first sales like every other
    platform fee."""
    fee = operator.effective_setup_fee
    if fee <= 0:
        return False
    if LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.SETUP_FEE
    ).exists():
        return False
    try:
        with db_transaction.atomic():
            LedgerEntry.objects.create(
                operator=operator,
                entry_type=LedgerEntry.Type.SETUP_FEE,
                amount=-fee,
                memo="One-time onboarding / setup fee",
            )
    except IntegrityError:
        return False
    audit("wallet_setup_fee_charged", operator=operator, amount=str(fee))
    return True


def credit_sale(tx) -> None:
    """Credit the ISP's wallet for a successful transaction, withholding the
    platform commission at source. Idempotent per transaction (DB constraint)."""
    operator = tx.operator
    gross = Decimal(tx.amount)
    # effective_* is 0 for the platform's own ISP — Danamo never bills itself
    rate = operator.effective_commission_pct
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
                    memo=f"{rate}% platform commission",
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


def request_payout(*, operator, amount: Decimal, user, method="mpesa", destination=None) -> Payout:
    """Funds are debited (held) immediately so concurrent requests can't
    double-spend the balance. `destination` carries the method-specific details
    (phone for M-Pesa; bank_name/account for bank).

    THE ONE-PAYOUT CAP: if a previous payout is still awaiting confirmation, no
    further payout may leave. The ISP gets their first withdrawal in full and at
    once — but that payout carries a code, and until they read it back we do not
    know the money actually landed where they said. Blocking here is what caps a
    wrong (or hijacked) destination at a single payout instead of an open drain.
    """
    from apps.core.settlement import (
        new_confirmation_code,
        payout_awaiting_confirmation,
    )

    destination = destination or {}
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount < MINIMUM_PAYOUT:
        raise WalletError(f"Minimum withdrawal is KSh {MINIMUM_PAYOUT}.")

    unconfirmed = payout_awaiting_confirmation(operator)
    if unconfirmed is not None:
        raise WalletError(
            "Confirm your last payout first. We sent a code with it — read it back "
            "from your statement and your payouts unlock permanently."
        )

    fields = {"method": method}
    if method == Payout.Method.BANK:
        if not (destination.get("bank_name") and destination.get("bank_account_number")):
            raise WalletError("Bank name and account number are required for a bank withdrawal.")
        fields.update(
            bank_name=destination["bank_name"],
            bank_account_number=destination["bank_account_number"],
            bank_account_name=destination.get("bank_account_name", ""),
        )
        dest_label = f"{fields['bank_name']} {fields['bank_account_number']}"
    else:
        if not destination.get("phone"):
            raise WalletError("An M-Pesa number is required.")
        fields["phone"] = destination["phone"]
        dest_label = fields["phone"]

    from .tariffs import payout_cost

    with db_transaction.atomic():
        op_locked = type(operator).objects.select_for_update().get(pk=operator.pk)
        if amount > wallet_balance(op_locked):
            raise WalletError("Withdrawal exceeds your wallet balance.")
        payout = Payout.objects.create(
            operator=op_locked,
            amount=amount,
            requested_by=user,
            platform_cost=payout_cost(amount, method),
            # An unconfirmed destination gets a code riding along with the money.
            # Free to send, and it proves the payout actually landed.
            confirmation_code=(
                "" if op_locked.settlement_verified_at else new_confirmation_code()
            ),
            **fields,
        )
        LedgerEntry.objects.create(
            operator=op_locked,
            entry_type=LedgerEntry.Type.PAYOUT,
            amount=-amount,
            payout=payout,
            memo=f"Withdrawal ({method}) to {dest_label}",
        )
    audit("payout_requested", operator=operator, actor=user, target=payout,
          amount=str(amount), method=method)
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
    operators = list(
        Operator.objects.filter(
            status=Operator.Status.ACTIVE, base_fee__gt=0, is_platform_owned=False
        )
    )
    for operator in operators:
        fee = operator.effective_base_fee
        if fee <= 0:
            continue
        if operator.in_base_fee_trial():
            continue  # first month free — base fee not yet started
        try:
            # Savepoint per charge: a duplicate-month conflict must not poison
            # the surrounding transaction
            with db_transaction.atomic():
                LedgerEntry.objects.create(
                    operator=operator,
                    entry_type=LedgerEntry.Type.BASE_FEE,
                    amount=-fee,
                    period=period,
                    memo=f"Platform subscription {period}",
                )
            charged += 1
        except IntegrityError:
            continue  # this month already charged
    return charged
