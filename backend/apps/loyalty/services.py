"""Loyalty earning: turn a payment into points, exactly once, against the right account.

Earn runs inside the payment's own transaction (so it commits or rolls back WITH the money),
and the ledger's one-earn-per-transaction constraint makes a replayed callback a no-op even
under a race. Redemption (cashing points in for account credit) is the next phase; the rules
are already configured here.
"""

import logging

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import F

from .models import LoyaltyAccount, LoyaltyLedgerEntry, LoyaltySettings

logger = logging.getLogger(__name__)


def settings_for(operator) -> LoyaltySettings:
    row, _ = LoyaltySettings.objects.get_or_create(operator=operator)
    return row


def _award(operator, phone: str, points: int, *, transaction=None, reason: str = "") -> bool:
    """Credit `points` to (operator, phone). Idempotent per transaction. Returns True if a
    fresh credit was made. Notifies best-effort on commit."""
    if points <= 0 or not phone:
        return False

    account, _ = LoyaltyAccount.objects.get_or_create(operator=operator, phone=phone)
    try:
        with db_transaction.atomic():
            LoyaltyLedgerEntry.objects.create(
                operator=operator,
                account=account,
                kind=LoyaltyLedgerEntry.Kind.EARN,
                points=points,
                transaction=transaction,
                reason=reason,
            )
            LoyaltyAccount.objects.filter(pk=account.pk).update(
                points_balance=F("points_balance") + points
            )
    except IntegrityError:
        # The one-earn-per-transaction constraint fired — already credited. No-op.
        return False

    account.refresh_from_db(fields=["points_balance"])
    _notify_earned(account, points)
    return True


def award_for_transaction(tx) -> bool:
    """Award points for a successful M-Pesa purchase, per the ISP's rule. Safe to call more
    than once for the same transaction — only the first credits."""
    cfg = LoyaltySettings.objects.filter(operator_id=tx.operator_id).first()
    if cfg is None or not cfg.is_enabled:
        return False
    points = cfg.points_for(tx.amount)
    if points <= 0:
        return False
    return _award(
        tx.operator, (tx.phone or "").strip(), points,
        transaction=tx, reason=f"Payment {tx.public_id}",
    )


def _notify_earned(account, points: int) -> None:
    try:
        from apps.notifications.models import Message
        from apps.notifications.services import _company_name, render, send_sms

        op = account.operator
        body = render(op, "points_earned", {
            "points": str(points),
            "points_balance": str(account.points_balance),
            "company_name": _company_name(op),
        })
        if body:
            send_sms(op, account.phone, body, category=Message.Category.OTHER)
    except Exception:
        logger.exception("Could not queue the loyalty-points SMS for %s", account.phone)


def summary(operator, *, search: str = "", top: int = 10) -> dict:
    """Programme health for the ISP: enrolment, points outstanding, and the top holders."""
    from django.db.models import Count, Sum

    accounts = LoyaltyAccount.objects.filter(operator=operator)
    agg = accounts.aggregate(n=Count("id"), pts=Sum("points_balance"))
    holders = accounts
    if search:
        holders = holders.filter(phone__icontains=search.strip())
    top_rows = holders.order_by("-points_balance", "phone")[:top]
    return {
        "accounts": agg["n"] or 0,
        "points_outstanding": agg["pts"] or 0,
        "top": [{"phone": a.phone, "points": a.points_balance} for a in top_rows],
    }
