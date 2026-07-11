"""Platform system health — is the machine that moves other people's money OK?

This is deliberately opinionated: it does not dump metrics, it answers questions
that have a right answer. Every check reports `ok` / `warn` / `crit`, and the
worst check decides the overall state. A green board means: no money is stranded,
no customer is unprovisioned, the fleet is reachable, and the workers are alive.

The checks are ordered by what actually hurts:
  1. money stranded (paid, not delivered / arrived with no home)
  2. workers dead (nothing gets provisioned or reconciled at all)
  3. fleet unreachable (an ISP's customers can't be cut off or turned on)
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import C2BPayment, Transaction
from apps.provisioning.models import Router, Session

from .permissions import IsPlatformStaff

OK, WARN, CRIT = "ok", "warn", "crit"
_RANK = {OK: 0, WARN: 1, CRIT: 2}

# A callback normally lands in seconds. Past this, the reconciliation beat should
# have swept it up — if it hasn't, something is wrong with the sweep or Daraja.
STUCK_PAYMENT_MINUTES = 15
# Provisioning runs on a worker; a session stuck pending this long means the
# customer PAID and has no internet. That is the worst thing this system can do.
STUCK_PROVISION_MINUTES = 10
ROUTER_STALE_HOURS = 2


def _check(key, label, state, value, detail):
    return {"key": key, "label": label, "state": state, "value": value, "detail": detail}


class PlatformHealthView(APIView):
    """Cross-tenant operational health. Platform staff only."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        now = timezone.now()
        checks = []

        # --- 1. Money stranded --------------------------------------------------
        stuck_tx = Transaction.objects.filter(
            status=Transaction.Status.PENDING,
            created_at__lte=now - timedelta(minutes=STUCK_PAYMENT_MINUTES),
        )
        n_stuck_tx = stuck_tx.count()
        checks.append(
            _check(
                "stuck_payments",
                "Payments awaiting a callback",
                CRIT if n_stuck_tx > 5 else WARN if n_stuck_tx else OK,
                n_stuck_tx,
                f"Pending for over {STUCK_PAYMENT_MINUTES} min. The reconciliation "
                "sweep queries Daraja for these — if the number keeps growing, the "
                "sweep or the callback URL is broken.",
            )
        )

        unmatched = C2BPayment.objects.filter(status=C2BPayment.Status.UNMATCHED)
        n_unmatched = unmatched.count()
        unmatched_value = unmatched.aggregate(v=Sum("amount"))["v"] or Decimal("0")
        checks.append(
            _check(
                "unmatched_payments",
                "Payments that matched no account",
                CRIT if n_unmatched else OK,
                n_unmatched,
                f"KSh {unmatched_value} arrived on the paybill with an account number "
                "we don't recognise. This is real customer money sitting unattributed — "
                "find the account and credit it.",
            )
        )

        # Paid, but the customer never got their internet.
        failed_sessions = Session.objects.filter(status=Session.Status.FAILED)
        stuck_sessions = Session.objects.filter(
            status=Session.Status.PENDING,
            created_at__lte=now - timedelta(minutes=STUCK_PROVISION_MINUTES),
        )
        n_undelivered = failed_sessions.count() + stuck_sessions.count()
        checks.append(
            _check(
                "undelivered_service",
                "Paid customers with no service",
                CRIT if n_undelivered else OK,
                n_undelivered,
                "Provisioning failed or never ran. These customers paid and have no "
                "internet — the single worst failure this system can produce.",
            )
        )

        # --- 2. Workers ---------------------------------------------------------
        workers = _ping_workers()
        checks.append(
            _check(
                "workers",
                "Background workers",
                OK if workers["reachable"] else CRIT,
                workers["count"],
                "Celery runs provisioning, reconciliation, invoicing and suspension. "
                "If it is down, nothing is delivered and nothing is billed."
                if not workers["reachable"]
                else "Responding to ping.",
            )
        )

        # --- 3. Fleet -----------------------------------------------------------
        routers = Router.objects.filter(is_active=True)
        total = routers.count()
        online = routers.filter(status=Router.Status.ONLINE).count()
        offline = routers.filter(status=Router.Status.OFFLINE).count()
        needs_onboarding = routers.filter(onboarding_required=True).count()
        stale = routers.filter(
            last_seen_at__lt=now - timedelta(hours=ROUTER_STALE_HOURS)
        ).count()

        checks.append(
            _check(
                "routers_offline",
                "Routers offline",
                CRIT if offline > 0 and offline == total else WARN if offline else OK,
                offline,
                "An offline router cannot provision new customers or cut off expired "
                "ones. Their hotspot keeps serving whoever is already on it.",
            )
        )
        checks.append(
            _check(
                "routers_reonboard",
                "Routers needing re-onboarding",
                WARN if needs_onboarding else OK,
                needs_onboarding,
                "The router rejected our credentials — almost always a factory reset. "
                "The ISP must re-run the setup script, or re-sync from their console.",
            )
        )

        overall = max((c["state"] for c in checks), key=lambda s: _RANK[s])

        return Response(
            {
                "scope": "all_isps",
                "status": overall,
                "checked_at": now,
                "checks": checks,
                "fleet": {
                    "total": total,
                    "online": online,
                    "offline": offline,
                    "pending": routers.filter(status=Router.Status.PENDING).count(),
                    "unknown": routers.filter(status=Router.Status.UNKNOWN).count(),
                    "needs_reonboarding": needs_onboarding,
                    "stale": stale,
                },
                "workers": workers,
                "money": {
                    "stuck_payments": n_stuck_tx,
                    "unmatched_payments": n_unmatched,
                    "unmatched_value": unmatched_value,
                    "undelivered_service": n_undelivered,
                },
            }
        )


def _ping_workers() -> dict:
    """Ask Celery who is alive. Never let a dead broker hang the request — a
    health check that hangs is worse than one that reports failure."""
    try:
        from config.celery import app as celery_app

        replies = celery_app.control.ping(timeout=1.0) or []
        names = [name for reply in replies for name in reply]
        return {"reachable": bool(names), "count": len(names), "names": names}
    except Exception:  # broker down, misconfigured, anything
        return {"reachable": False, "count": 0, "names": []}
