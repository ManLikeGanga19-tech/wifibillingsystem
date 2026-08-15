"""Loyalty earning: turn a payment into points, exactly once, against the right account.

Earn runs inside the payment's own transaction (so it commits or rolls back WITH the money),
and the ledger's one-earn-per-transaction constraint makes a replayed callback a no-op even
under a race. Redemption (cashing points in for account credit) is the next phase; the rules
are already configured here.
"""

import logging
from decimal import ROUND_CEILING, Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import F

from .models import LoyaltyAccount, LoyaltyLedgerEntry, LoyaltyRedemption, LoyaltySettings

logger = logging.getLogger(__name__)


class LoyaltyError(Exception):
    """A refused redemption/adjustment — a message safe to show the ISP."""


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


def points_needed_for(cfg: LoyaltySettings, plan) -> int:
    """How many points a `plan` costs at this ISP's rate, rounded UP. 0 if the ISP hasn't set
    a per-point value (redemption is off until they do)."""
    if not cfg.value_per_point or cfg.value_per_point <= 0:
        return 0
    return int((Decimal(plan.price) / cfg.value_per_point).to_integral_value(ROUND_CEILING))


def account_for(operator, phone: str) -> LoyaltyAccount | None:
    return LoyaltyAccount.objects.filter(operator=operator, phone=(phone or "").strip()).first()


@db_transaction.atomic
def redeem_for_voucher(operator, phone: str, plan, *, actor=None) -> LoyaltyRedemption:
    """Spend a subscriber's points on a REWARD VOUCHER for `plan` — the redemption flow.

    Points are the currency; `value_per_point` sets the exchange rate, `min_redeem_points` the
    floor. Debits the ledger and mints a single unused voucher (the code the customer uses at
    the hotspot) in ONE transaction under a row lock, so points can never be spent twice or
    debited without a voucher to show for it."""
    from apps.vouchers.models import Voucher
    from apps.vouchers.services import _generate_code

    cfg = settings_for(operator)
    if not cfg.is_enabled:
        raise LoyaltyError("This ISP's loyalty programme is switched off.")
    if plan.operator_id != operator.id:
        raise LoyaltyError("That plan belongs to a different ISP.")
    cost = points_needed_for(cfg, plan)
    if cost <= 0:
        raise LoyaltyError("Set a value per point before customers can redeem.")

    # Lock the account row so a concurrent redeem can't double-spend the same balance.
    account = (
        LoyaltyAccount.objects.select_for_update()
        .filter(operator=operator, phone=(phone or "").strip())
        .first()
    )
    if account is None:
        raise LoyaltyError("No loyalty account for that number.")
    floor = max(cfg.min_redeem_points, cost)
    if account.points_balance < floor:
        raise LoyaltyError(
            f"Not enough points: needs {floor}, has {account.points_balance}."
        )

    # Mint the reward voucher (retry the astronomically-rare code collision).
    for _attempt in range(5):
        code = _generate_code(prefix="RW")
        if not Voucher.objects.filter(code=code).exists():
            break
    else:
        raise LoyaltyError("Could not allocate a voucher code — please retry.")
    voucher = Voucher.objects.create(
        operator=operator, plan=plan, code=code, created_by=actor,
    )

    value = (cfg.value_per_point * cost).quantize(Decimal("0.01"))
    LoyaltyLedgerEntry.objects.create(
        operator=operator, account=account, kind=LoyaltyLedgerEntry.Kind.REDEEM,
        points=-cost, reason=f"Redeemed for {plan.name} (voucher {code})",
    )
    LoyaltyAccount.objects.filter(pk=account.pk).update(
        points_balance=F("points_balance") - cost
    )
    redemption = LoyaltyRedemption.objects.create(
        operator=operator, account=account, plan=plan, points_spent=cost,
        value_kes=value, voucher=voucher, actor=actor if getattr(actor, "pk", None) else None,
    )

    from apps.core.services import audit

    audit("loyalty_redeemed", operator=operator, actor=actor, target=account,
          phone=account.phone, points=cost, plan=plan.name, voucher=code)
    account.refresh_from_db(fields=["points_balance"])
    _notify_redeemed(account, plan, code)
    return redemption


def adjust_points(operator, phone: str, points: int, *, reason: str, actor=None) -> LoyaltyAccount:
    """Manually credit (+) or debit (-) a subscriber's points, with a recorded reason — the
    goodwill grant / correction lever. Never lets a balance go negative."""
    points = int(points)
    if points == 0:
        raise LoyaltyError("An adjustment must be a non-zero number of points.")
    if not (reason or "").strip():
        raise LoyaltyError("An adjustment needs a reason.")

    with db_transaction.atomic():
        account, _ = LoyaltyAccount.objects.select_for_update().get_or_create(
            operator=operator, phone=(phone or "").strip()
        )
        if points < 0 and account.points_balance + points < 0:
            raise LoyaltyError(
                f"Can't remove {-points}: the account only has {account.points_balance}."
            )
        LoyaltyLedgerEntry.objects.create(
            operator=operator, account=account, kind=LoyaltyLedgerEntry.Kind.ADJUST,
            points=points, reason=reason.strip()[:120],
        )
        LoyaltyAccount.objects.filter(pk=account.pk).update(
            points_balance=F("points_balance") + points
        )

    from apps.core.services import audit

    audit("loyalty_points_adjusted", operator=operator, actor=actor, target=account,
          phone=account.phone, points=points, reason=reason.strip())
    account.refresh_from_db(fields=["points_balance"])
    return account


def _notify_redeemed(account, plan, code: str) -> None:
    try:
        from apps.notifications.models import Message
        from apps.notifications.services import _company_name, render, send_sms

        op = account.operator
        body = render(op, "points_redeemed", {
            "plan": plan.name,
            "code": code,
            "points_balance": str(account.points_balance),
            "company_name": _company_name(op),
        })
        if body:
            send_sms(op, account.phone, body, category=Message.Category.OTHER)
    except Exception:
        logger.exception("Could not queue the redemption SMS for %s", account.phone)


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
