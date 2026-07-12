"""Settlement accounts: plug-and-play in, confirmed on the way out.

The ISP's paybill/bank is where WE pay THEM. Customers never touch it.

**Registering it is instant.** Type it in, payments switch on. We deliberately do
NOT spend money proving accounts up front: most signups never trade a shilling, and
paying a transfer fee to verify idle accounts is a straight loss on our least
valuable users.

**The first payout proves it, for free.** The ISP gets their full money immediately;
that payout carries a confirmation code; they read it back. Until they do, no SECOND
payout leaves. So a wrong destination is capped at one payout, not an open drain.

**What this really defends is ACCOUNT TAKEOVER.** Verifying at signup would have done
nothing about it — the account is already verified before an attacker changes it. The
attack is: get into an ISP's console, quietly swap the payout destination, drain the
wallet. So changing a confirmed account RE-ARMS the whole cycle and emails the owner.
An attacker gets at most one payout, and the real owner gets told.

Why the paybill is our KYC bar at all: to be issued one (or a business bank account),
Safaricom/the bank already ran full identity checks on that business. We inherit them
for free. A shell company cannot produce one.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import Operator
from .services import audit

logger = logging.getLogger(__name__)

#: Unambiguous alphabet — no O/0, I/1, S/5. The ISP reads this off an M-Pesa SMS or a
#: bank statement and types it back; every confusable character is a support ticket.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ2346789"
CODE_PREFIX = "WOS-"
MAX_ATTEMPTS = 5


class SettlementError(Exception):
    """Something the ISP can fix; safe to show them."""


def new_confirmation_code() -> str:
    """Rides along on a real payout, so it costs us nothing to send."""
    return CODE_PREFIX + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))


# ---- register (plug and play) ------------------------------------------------


def set_settlement_account(operator: Operator, *, method: str, actor=None, **fields) -> Operator:
    """Tell us where to pay you. Instant — this is what switches payments ON.

    Changing an already-CONFIRMED account re-arms confirmation and warns the owner:
    that swap is exactly what an attacker who got into the console would do.
    """
    was_confirmed = operator.settlement_verified_at is not None
    old_destination = operator.settlement_destination

    if method == Operator.Settlement.PAYBILL:
        paybill = (fields.get("settlement_paybill") or "").strip()
        if not paybill.isdigit():
            raise SettlementError("A paybill number must be digits only.")
        operator.settlement_paybill = paybill
        operator.settlement_name = (fields.get("settlement_name") or "").strip()
        if not operator.settlement_name:
            raise SettlementError("Tell us the business name registered on that paybill.")
    elif method == Operator.Settlement.BANK:
        bank = (fields.get("payout_bank_name") or "").strip()
        acct = (fields.get("payout_bank_account_number") or "").strip()
        if not (bank and acct):
            raise SettlementError("Bank name and account number are both required.")
        operator.payout_bank_name = bank
        operator.payout_bank_account_number = acct
        operator.payout_bank_account_name = (
            fields.get("payout_bank_account_name") or ""
        ).strip()
        operator.settlement_name = operator.payout_bank_account_name
    else:
        raise SettlementError("Choose a paybill or a bank account.")

    operator.settlement_method = method
    # A new destination is an unconfirmed destination — always.
    operator.settlement_verified_at = None
    operator.verification_attempts = 0
    operator.save()

    audit(
        "settlement_account_set",
        operator=operator,
        actor=actor,
        target=operator,
        method=method,
        destination=operator.settlement_destination,
        replaced_confirmed_account=was_confirmed,
    )

    if was_confirmed:
        # The takeover tripwire. Free, and it reaches the real owner even if the
        # attacker is sitting in the console.
        _warn_destination_changed(operator, old_destination)

    # Plug and play: having somewhere to be paid IS the bar. Go live.
    if operator.status != Operator.Status.ACTIVE:
        activate_operator(operator, actor=actor, reason="settlement account added")

    return operator


# ---- confirm (after the first payout lands) ----------------------------------


def confirm_payout(operator: Operator, submitted: str, *, actor=None) -> bool:
    """The ISP reads back the code that rode along with their first payout.

    That proves the money actually landed where they said it should, and unlocks
    every payout after this one.
    """
    from apps.billing.models import Payout

    if operator.settlement_verified_at:
        return True  # idempotent

    pending = (
        Payout.objects.filter(
            operator=operator, status=Payout.Status.PAID, confirmed_at__isnull=True
        )
        .exclude(confirmation_code="")
        .order_by("-processed_at")
        .first()
    )
    if pending is None:
        raise SettlementError(
            "There's nothing to confirm yet. Withdraw once, then confirm the code "
            "that arrives with it."
        )

    if operator.verification_attempts >= MAX_ATTEMPTS:
        raise SettlementError(
            "Too many incorrect codes. Contact support to unlock your payouts."
        )

    guess = (submitted or "").strip().upper().replace(" ", "")
    if not guess.startswith(CODE_PREFIX):
        guess = CODE_PREFIX + guess  # they typed just the code, not the prefix

    if not secrets.compare_digest(guess, pending.confirmation_code):
        operator.verification_attempts += 1
        operator.save(update_fields=["verification_attempts", "updated_at"])
        left = MAX_ATTEMPTS - operator.verification_attempts
        audit(
            "settlement_confirmation_failed",
            operator=operator,
            actor=actor,
            target=operator,
            attempts=operator.verification_attempts,
        )
        if left <= 0:
            raise SettlementError(
                "Too many incorrect codes. Contact support to unlock your payouts."
            )
        raise SettlementError(f"That code doesn't match. {left} attempt(s) left.")

    with db_transaction.atomic():
        pending.confirmed_at = timezone.now()
        pending.save(update_fields=["confirmed_at", "updated_at"])
        operator.settlement_verified_at = timezone.now()
        operator.verification_attempts = 0
        operator.save(
            update_fields=["settlement_verified_at", "verification_attempts", "updated_at"]
        )

    audit(
        "settlement_confirmed",
        operator=operator,
        actor=actor,
        target=operator,
        destination=operator.settlement_destination,
        payout=pending.id,
    )
    logger.info("%s confirmed their payout destination", operator.slug)
    return True


def payout_awaiting_confirmation(operator: Operator):
    """A paid-out payout whose code has not been read back. While one exists, no
    further payout may leave — that is what caps a wrong or hijacked destination at a
    single payout instead of an unbounded drain."""
    from apps.billing.models import Payout

    if operator.settlement_verified_at:
        return None
    return (
        Payout.objects.filter(
            operator=operator, status=Payout.Status.PAID, confirmed_at__isnull=True
        )
        .exclude(confirmation_code="")
        .order_by("-processed_at")
        .first()
    )


# ---- go live -----------------------------------------------------------------


@db_transaction.atomic
def activate_operator(operator: Operator, *, actor=None, reason: str = "") -> int:
    """Flip the money gate ON. The single place an ISP becomes able to earn.

    Returns the number of held customer payments released. Idempotent.
    """
    from apps.payments.c2b import release_held_payments

    if operator.approved_at is None:
        operator.approved_at = timezone.now()
    operator.status = Operator.Status.ACTIVE
    # The free month starts when they can actually EARN — not when they filled in a
    # form. Only ever set once.
    if operator.trial_ends_at is None:
        operator.trial_ends_at = timezone.localdate() + timedelta(days=30)
    operator.save(
        update_fields=["status", "approved_at", "trial_ends_at", "updated_at"]
    )

    # Everything their customers paid while they were still setting up is credited
    # now. Nobody loses a shilling because WE made them wait.
    released = release_held_payments(operator)

    audit(
        "tenant_activated",
        operator=operator,
        actor=actor,
        target=operator,
        reason=reason,
        released_payments=released,
    )
    logger.info("%s is LIVE (%s); released %s held payment(s)", operator.slug, reason, released)
    return released


# ---- email -------------------------------------------------------------------


def _warn_destination_changed(operator: Operator, old: str) -> None:
    """Reaches the real owner even if an attacker is the one sitting in the console."""
    to = operator.contact_email
    if not to:
        return
    try:
        send_mail(
            "Your WIFI.OS payout account was changed",
            f"Hi,\n\n"
            f"The account we pay {operator.name} into has just been changed.\n\n"
            f"    Was:  {old or '(none)'}\n"
            f"    Now:  {operator.settlement_destination}\n\n"
            "If you did this, nothing more is needed — your next payout will carry a "
            "code to confirm the new account.\n\n"
            "IF YOU DID NOT DO THIS, someone may have access to your console. Change "
            "your password immediately and contact us.\n\n"
            "— WIFI.OS",
            getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wifios.co.ke"),
            [to],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not warn %s that their payout account changed", operator.slug)
