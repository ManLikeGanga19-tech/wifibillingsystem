"""Settlement accounts and micro-transfer verification.

The ISP's paybill/bank is NOT a collection account — customers never pay it. It is
where WE pay THEM, and it doubles as our KYC bar:

    To be issued a paybill (or a business bank account), Safaricom/the bank already
    ran full KYC on that business. We inherit it for free. A shell company cannot
    produce one.

But anyone can *type* "123456". So we prove control the way banks have for decades:
send a few shillings carrying a random reference, and ask them to read it back off
their own statement. Unfakeable without access to the account, automated, and it
costs a rounding error against the money-laundering risk it retires.

Verification is what flips an ISP live — money on, trial starts, held payments
released. See docs/ONBOARDING_ARCHITECTURE.md §3b.
"""

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import Operator
from .services import audit

logger = logging.getLogger(__name__)

#: Unambiguous alphabet — no O/0, I/1, S/5. The ISP has to read this off an SMS or
#: a statement and type it back; every confusable character is a support ticket.
_REF_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ2346789"
REF_PREFIX = "WOS-"

MAX_ATTEMPTS = 3
#: A stale challenge is a weak challenge.
CHALLENGE_TTL_HOURS = 72

#: We send a small, RANDOM amount as well as the reference. The reference is the
#: real proof; the amount is the fallback if it turns out a B2B recipient cannot see
#: a reference we set (an open question with Safaricom — see the tariff RFI).
MIN_AMOUNT = Decimal("5.00")
MAX_AMOUNT = Decimal("19.00")


class SettlementError(Exception):
    """Something the ISP can fix; safe to show them."""


def _new_ref() -> str:
    return REF_PREFIX + "".join(secrets.choice(_REF_ALPHABET) for _ in range(4))


def _new_amount() -> Decimal:
    return MIN_AMOUNT + Decimal(secrets.randbelow(int(MAX_AMOUNT - MIN_AMOUNT) + 1))


# ---- 1. the ISP tells us where to pay them ----------------------------------


def set_settlement_account(operator: Operator, *, method: str, **fields) -> Operator:
    """Record where we should settle. Changing it ALWAYS resets verification — a new
    account is a new claim and has to be proved again, or an ISP could verify an
    account they control and then swap in one they do not."""
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
    # A new account is an unproven account.
    operator.settlement_verified_at = None
    operator.verification_ref = ""
    operator.verification_amount = None
    operator.verification_sent_at = None
    operator.verification_attempts = 0
    operator.save()

    audit(
        "settlement_account_set",
        operator=operator,
        target=operator,
        method=method,
        destination=operator.settlement_destination,
    )
    return operator


# ---- 2. we send them a few shillings ----------------------------------------


def send_micro_transfer(operator: Operator) -> Operator:
    """Send the proof-of-control payment. Returns the operator with a live challenge.

    The plaintext reference is NOT returned to the caller: the whole point is that
    only someone who can see the destination account's statement learns it.
    """
    if not operator.has_settlement_account:
        raise SettlementError("Add a settlement account first.")
    if operator.settlement_verified_at:
        raise SettlementError("This account is already verified.")

    operator.verification_ref = _new_ref()
    operator.verification_amount = _new_amount()
    operator.verification_sent_at = timezone.now()
    operator.verification_attempts = 0
    operator.save(
        update_fields=[
            "verification_ref",
            "verification_amount",
            "verification_sent_at",
            "verification_attempts",
            "updated_at",
        ]
    )

    _disburse(operator)

    audit(
        "settlement_verification_sent",
        operator=operator,
        target=operator,
        destination=operator.settlement_destination,
        amount=str(operator.verification_amount),
        # The reference is recorded in the audit trail (support needs it to help a
        # confused ISP) but is never returned over the API.
        reference=operator.verification_ref,
    )
    return operator


def _disburse(operator: Operator) -> None:
    """Actually move the money.

    Today this is a no-op stub: real payouts are executed manually and the I&M /
    Daraja B2B rails are not wired yet (see docs/PRE_STAGING_CHECKLIST.md). It is
    isolated behind this one function on purpose, so switching to the real rail is a
    single change and never touches the verification logic.
    """
    logger.info(
        "MICRO-TRANSFER: KSh %s ref=%s -> %s [%s]",
        operator.verification_amount,
        operator.verification_ref,
        operator.settlement_destination,
        "STUB — no real rail wired yet",
    )


# ---- 3. they read the reference back ----------------------------------------


def verify_settlement(operator: Operator, submitted: str, *, actor=None) -> bool:
    """The moment of truth. A correct reference proves they can see that account's
    statement, which proves they control it.

    On success the ISP goes LIVE (unless the platform has forced manual review).
    """
    if operator.settlement_verified_at:
        return True  # idempotent

    if not operator.verification_ref:
        raise SettlementError("No verification is in progress. Request a new transfer.")

    expired = timezone.now() - operator.verification_sent_at > timedelta(
        hours=CHALLENGE_TTL_HOURS
    )
    if expired:
        raise SettlementError("That verification expired. Request a new transfer.")

    if operator.verification_attempts >= MAX_ATTEMPTS:
        raise SettlementError(
            "Too many incorrect attempts. Request a new transfer to try again."
        )

    guess = (submitted or "").strip().upper().replace(" ", "")
    if not guess.startswith(REF_PREFIX):
        guess = REF_PREFIX + guess  # they typed just the code, not the prefix

    if not secrets.compare_digest(guess, operator.verification_ref):
        operator.verification_attempts += 1
        operator.save(update_fields=["verification_attempts", "updated_at"])
        left = MAX_ATTEMPTS - operator.verification_attempts
        audit(
            "settlement_verification_failed",
            operator=operator,
            actor=actor,
            target=operator,
            attempts=operator.verification_attempts,
        )
        if left <= 0:
            raise SettlementError(
                "Too many incorrect attempts. Request a new transfer to try again."
            )
        raise SettlementError(f"That reference doesn't match. {left} attempt(s) left.")

    operator.settlement_verified_at = timezone.now()
    operator.save(update_fields=["settlement_verified_at", "updated_at"])
    audit(
        "settlement_verified",
        operator=operator,
        actor=actor,
        target=operator,
        destination=operator.settlement_destination,
    )

    if not getattr(settings, "SETTLEMENT_REQUIRES_MANUAL_REVIEW", False):
        activate_operator(operator, actor=actor, reason="settlement verified")
    else:
        logger.info(
            "%s verified settlement but manual review is forced — awaiting a human",
            operator.slug,
        )
    return True


# ---- 4. go live -------------------------------------------------------------


@db_transaction.atomic
def activate_operator(operator: Operator, *, actor=None, reason: str = "") -> int:
    """Flip the money gate ON. The single place an ISP becomes able to earn.

    Returns the number of held customer payments released. Idempotent: activating an
    already-active ISP releases nothing twice.
    """
    from apps.payments.c2b import release_held_payments

    first_activation = operator.approved_at is None

    operator.status = Operator.Status.ACTIVE
    if first_activation:
        operator.approved_at = timezone.now()
    # The free month starts when they can actually EARN — not when they filled in a
    # form. Only ever set once.
    if operator.trial_ends_at is None:
        operator.trial_ends_at = timezone.localdate() + timedelta(days=30)
    operator.save(
        update_fields=["status", "approved_at", "trial_ends_at", "updated_at"]
    )

    # Everything their customers paid while we were verifying them is credited now.
    # Nobody loses a shilling because WE made them wait.
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
