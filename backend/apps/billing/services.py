"""Wallet operations. Every function here is money-critical: atomic, idempotent,
and audited."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.services import audit

from .models import LedgerEntry, Payout, Settlement

MINIMUM_PAYOUT = Decimal("100.00")


class WalletError(Exception):
    pass


def withdrawable_balance(operator) -> Decimal:
    """What this ISP may actually take out — money WIFI.OS is holding for them.

    THE INVARIANT of the finance module. A sale settled straight into the ISP's own
    gateway is real revenue and appears in their reports, but we never received that cash:
    counting it here would let them withdraw money we do not have, on every direct sale,
    silently. So custody is filtered, not assumed.
    """
    return LedgerEntry.objects.filter(
        operator=operator, settlement=Settlement.PLATFORM
    ).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")


#: The old name, kept because a dozen call sites say "wallet balance" and mean exactly
#: this: the money we hold. Anything that means REVENUE must not use it — see
#: reports.revenue_summary.
wallet_balance = withdrawable_balance


def recorded_revenue(operator) -> Decimal:
    """Everything they sold, whoever held the cash. The basis for reports and for the fee
    we invoice — NOT for payouts."""
    return LedgerEntry.objects.filter(
        operator=operator, entry_type=LedgerEntry.Type.SALE
    ).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")


def amount_owed(operator) -> Decimal:
    """What the ISP owes us that we CANNOT cover from money we already hold — the number
    the enforcement ladder runs on.

    Fees live on the platform account; custody lives in the wallet. An aggregator ISP with
    a healthy wallet owes us nothing in practice — we simply take our fee from what we
    hold. A direct ISP has no wallet, so their whole platform debt stands. Netting here (a
    pure read) does what a nightly wallet->platform sweep would, with nothing to drift.
    """
    from apps.billing.platform_account import debt

    return max(Decimal("0.00"), debt(operator) - withdrawable_balance(operator))


def available_to_withdraw(operator) -> Decimal:
    """What they may actually take out: money we hold, minus what they owe us. We do not
    hand back cash while a fee sits unpaid — that would be paying an ISP their sales and
    then chasing them for our cut."""
    from apps.billing.platform_account import debt

    return max(Decimal("0.00"), withdrawable_balance(operator) - debt(operator))


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

    from .models import PlatformLedgerEntry
    from .platform_account import accrue_fee
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
        # Onto the platform account (what they owe us), not the wallet. The wallet is now
        # purely custody; every fee lives in one place so the exposure check and the invoice
        # see the same number. accrue_fee is idempotent per (operator, month).
        if accrue_fee(
            operator, fee, reason=PlatformLedgerEntry.Reason.PPPOE_FEE, period=period,
            memo=f"PPPoE platform fee {period} ({active} users)",
        ):
            charged += 1
    return charged


def charge_setup_fee(operator) -> bool:
    """One-time onboarding fee, billed to the ISP wallet when it is approved.
    Idempotent: at most one SETUP_FEE entry per operator, ever. Returns True if
    a charge was made. Recouped from the tenant's first sales like every other
    platform fee."""
    from .models import PlatformLedgerEntry
    from .platform_account import accrue_fee

    fee = operator.effective_setup_fee
    if fee <= 0:
        return False
    # Onto the platform account. period="once" reuses the (operator, reason, period) unique
    # constraint as a charge-exactly-once guard — the wallet stays purely custody.
    entry = accrue_fee(
        operator, fee, reason=PlatformLedgerEntry.Reason.SETUP_FEE, period="once",
        memo="One-time onboarding / setup fee",
    )
    if entry is None:
        return False
    audit("wallet_setup_fee_charged", operator=operator, amount=str(fee))
    return True


def credit_sale(tx, *, settlement: str = Settlement.PLATFORM) -> None:
    """Record a successful sale. Idempotent per transaction (DB constraint).

    Where the cash landed decides how we are paid, and the two cases are genuinely
    different:

    * `platform` — the money is in OUR account, so we withhold commission at source and
      the remainder is theirs to withdraw. This is the aggregator path.
    * `direct` — the money went straight to the ISP's own gateway. We cannot withhold from
      money we never held, so instead the commission is ACCRUED to the platform account as
      a debt (accrue_fee below): tracked live, on the monthly invoice, collected by STK.
      Nothing goes unnoticed.

    Both write the SALE, because both are revenue.
    """
    operator = tx.operator
    gross = Decimal(tx.amount)
    direct = settlement == Settlement.DIRECT

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
                settlement=settlement,
                memo=f"Sale {tx.mpesa_receipt or tx.checkout_request_id}",
            )
            if commission > 0 and not direct:
                # AGGREGATOR: we hold the cash, so we withhold our cut at source. It never
                # becomes a debt because it was never theirs to withdraw.
                LedgerEntry.objects.create(
                    operator=operator,
                    entry_type=LedgerEntry.Type.COMMISSION,
                    amount=-commission,
                    transaction=tx,
                    settlement=Settlement.PLATFORM,
                    memo=f"{rate}% platform commission",
                )
    except IntegrityError:
        return  # replayed callback — already credited

    if commission > 0 and direct:
        # DIRECT: the money went to the ISP, so there is nothing to withhold from. The
        # commission becomes a debt on the platform account — tracked live, on the invoice,
        # collected by STK. Nothing goes unnoticed. Idempotent per sale (unique on tx), so
        # this sits safely OUTSIDE the sale transaction above and a replay is a no-op.
        from apps.billing.models import PlatformLedgerEntry
        from apps.billing.platform_account import accrue_fee

        accrue_fee(
            operator,
            commission,
            reason=PlatformLedgerEntry.Reason.COMMISSION,
            transaction=tx,
            memo=f"{rate}% commission on direct sale {tx.mpesa_receipt or tx.pk}",
        )
    audit(
        "wallet_sale_credited",
        operator=operator,
        target=tx,
        gross=str(gross),
        commission=str(commission) if not direct else "0.00",
        settlement=settlement,
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
        # AVAILABLE, not just withdrawable: money we hold MINUS what they owe us. A sale
        # that settled to the ISP's own gateway is money we never received (so it is not
        # withdrawable), and any unpaid platform fee is held back here rather than chased
        # later.
        if amount > available_to_withdraw(op_locked):
            raise WalletError("Withdrawal exceeds your available balance.")
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

    from .models import PlatformLedgerEntry
    from .platform_account import accrue_fee

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
        # Onto the platform account (what they owe us). accrue_fee is idempotent per
        # (operator, month), so a re-run of the beat task cannot double-charge.
        if accrue_fee(
            operator, fee, reason=PlatformLedgerEntry.Reason.BASE_FEE, period=period,
            memo=f"Platform subscription {period}",
        ):
            charged += 1
    return charged
