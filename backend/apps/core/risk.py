"""Platform fraud / risk signals — read-only detection, never enforcement.

A signal is a HINT for a human to look, not an automatic action: this module only reads the
ledger and the lifecycle log and surfaces tenants worth a second glance. Every threshold is a
named constant so it can be tuned without touching logic, and every finding carries the raw
numbers behind it so the reviewer can judge it. Demo and the platform's own tenant are
excluded — they can't defraud us. Deliberately conservative: a missed signal is cheaper than
a false alarm that trains staff to ignore the screen.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Operator, TenantLifecycleEvent

# --- thresholds (tune here, not in the logic) --------------------------------------------
SPIKE_LOOKBACK_DAYS = 14
SPIKE_MULT = 4.0                       # today ≥ this × the trailing daily average
SPIKE_FLOOR = Decimal("20000")         # …and at least this many KES (ignore small noise)
SPIKE_MIN_BASELINE_DAYS = 3            # need some history before a "spike" means anything

CYCLING_DAYS = 90
CYCLING_MIN_SUSPENDS = 3               # this many suspensions in the window = churn abuse

PAYOUT_LOOKBACK_DAYS = 7
PAYOUT_FLOOR = Decimal("50000")        # a payout smaller than this is never flagged
PAYOUT_FRACTION = 0.6                  # …flag when it's this share of lifetime collections
PAYOUT_AFTER_SETTLEMENT_DAYS = 3       # big payout this soon after settlement (re)verify = high

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _real_operators():
    return Operator.objects.exclude(is_demo=True).exclude(is_platform_owned=True)


def _finding(op, signal, severity, headline, **detail):
    return {
        "operator": op.id if hasattr(op, "id") else op["id"],
        "name": op.name if hasattr(op, "name") else op["name"],
        "slug": op.slug if hasattr(op, "slug") else op["slug"],
        "signal": signal,
        "severity": severity,
        "headline": headline,
        "detail": detail,
    }


def _collections_by_op_day(since):
    """{operator_id: {date: total_kes}} from both money-in rails (STK txns + matched C2B)."""
    from apps.payments.models import C2BPayment, Transaction

    out: dict[int, dict] = defaultdict(lambda: defaultdict(Decimal))
    txns = (
        Transaction.objects.filter(
            status__in=Transaction.SUCCESS_STATUSES, created_at__gte=since, operator__isnull=False
        )
        .annotate(d=TruncDate("created_at"))
        .values("operator", "d")
        .annotate(v=Sum("amount"))
    )
    for r in txns:
        out[r["operator"]][r["d"]] += r["v"] or Decimal("0")
    c2b = (
        C2BPayment.objects.filter(
            status=C2BPayment.Status.MATCHED, received_at__gte=since, operator__isnull=False
        )
        .annotate(d=TruncDate("received_at"))
        .values("operator", "d")
        .annotate(v=Sum("amount"))
    )
    for r in c2b:
        out[r["operator"]][r["d"]] += r["v"] or Decimal("0")
    return out


def _collection_spikes(now):
    """A tenant whose collections TODAY dwarf its own trailing daily average — the shape of
    card-testing or a laundering run pushed through one ISP's account."""
    since = now - timedelta(days=SPIKE_LOOKBACK_DAYS)
    today = timezone.localdate()
    by_op = _collections_by_op_day(since)
    ops = {o.id: o for o in _real_operators().filter(id__in=by_op.keys())}

    findings = []
    for op_id, per_day in by_op.items():
        op = ops.get(op_id)
        if op is None:
            continue
        today_total = per_day.get(today, Decimal("0"))
        prior = [v for d, v in per_day.items() if d != today]
        if today_total < SPIKE_FLOOR or len(prior) < SPIKE_MIN_BASELINE_DAYS:
            continue
        avg = sum(prior) / len(prior)
        if avg <= 0:
            continue
        ratio = float(today_total) / float(avg)
        if ratio < SPIKE_MULT:
            continue
        severity = "high" if ratio >= 2 * SPIKE_MULT else "medium"
        findings.append(_finding(
            op, "collection_spike", severity,
            f"Collections today are {ratio:.1f}× the {len(prior)}-day average",
            today=str(today_total), daily_avg=str(round(avg, 2)), ratio=round(ratio, 1),
        ))
    return findings


def _duplicate_identity():
    """Two or more tenants sharing a contact phone or email — a hallmark of one actor spinning
    up several tenants (trial farming, or splitting fraud across accounts)."""
    findings = []
    for field, label in (("contact_phone", "phone"), ("contact_email", "email")):
        rows = (
            _real_operators().exclude(**{f"{field}": ""})
            .values(field)
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        for r in rows:
            shared = list(
                _real_operators().filter(**{field: r[field]})
                .values("id", "name", "slug")
            )
            for op in shared:
                findings.append(_finding(
                    op, "duplicate_identity", "medium" if len(shared) == 2 else "high",
                    f"Shares a contact {label} with {len(shared) - 1} other tenant(s)",
                    field=label, value=r[field], shared_with=[s["slug"] for s in shared],
                ))
    return findings


def _reactivation_cycling(now):
    """A tenant suspended and reactivated over and over — someone gaming trials/free windows,
    or an account in enough trouble to warrant a look."""
    since = now - timedelta(days=CYCLING_DAYS)
    rows = (
        TenantLifecycleEvent.objects.filter(
            event=TenantLifecycleEvent.Event.SUSPENDED, occurred_at__gte=since,
            operator__isnull=False,
        )
        .values("operator")
        .annotate(n=Count("id"))
        .filter(n__gte=CYCLING_MIN_SUSPENDS)
    )
    ops = {o.id: o for o in _real_operators().filter(id__in=[r["operator"] for r in rows])}
    findings = []
    for r in rows:
        op = ops.get(r["operator"])
        if op is None:
            continue
        findings.append(_finding(
            op, "reactivation_cycling", "high" if r["n"] >= 2 * CYCLING_MIN_SUSPENDS else "medium",
            f"Suspended {r['n']} times in {CYCLING_DAYS} days",
            suspensions=r["n"], window_days=CYCLING_DAYS,
        ))
    return findings


def _large_payouts(now):
    """A big money-OUT event relative to what a tenant has ever collected — a drain. Higher
    severity when it lands right after the settlement account was (re)verified, the classic
    account-takeover-then-cash-out shape."""
    from apps.billing.models import LedgerEntry, Payout
    from apps.payments.models import C2BPayment, Transaction

    since = now - timedelta(days=PAYOUT_LOOKBACK_DAYS)
    payouts = (
        Payout.objects.filter(created_at__gte=since, amount__gte=PAYOUT_FLOOR)
        .exclude(status=Payout.Status.REJECTED)
        .select_related("operator")
    )
    findings = []
    for p in payouts:
        op = p.operator
        if op is None or op.is_demo or op.is_platform_owned:
            continue
        # lifetime money-in for context (STK + credited ledger). Cheap enough per flagged row.
        collected = (
            Transaction.objects.filter(
                operator=op, status__in=Transaction.SUCCESS_STATUSES
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        )
        sales = (
            LedgerEntry.objects.filter(operator=op, entry_type=LedgerEntry.Type.SALE)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0")
        )
        # PPPoE ISPs collect via C2B, not STK — count it too, or a paybill-only tenant looks
        # like it never collected and every payout reads as a 100000% drain.
        c2b = (
            C2BPayment.objects.filter(operator=op, status=C2BPayment.Status.MATCHED)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0")
        )
        baseline = max(collected + c2b, sales, Decimal("1"))
        fraction = float(p.amount) / float(baseline)
        fresh_settlement = (
            op.settlement_verified_at is not None
            and (p.created_at - op.settlement_verified_at) <= timedelta(
                days=PAYOUT_AFTER_SETTLEMENT_DAYS
            )
        )
        if fraction < PAYOUT_FRACTION and not fresh_settlement:
            continue
        severity = "high" if fresh_settlement else "medium"
        findings.append(_finding(
            op, "large_payout", severity,
            (f"Payout of KES {p.amount:,.0f} "
             + ("just after a settlement change" if fresh_settlement
                else f"is {fraction * 100:.0f}% of lifetime collections")),
            amount=str(p.amount), lifetime_collected=str(baseline),
            fraction=round(fraction, 2), soon_after_settlement_change=fresh_settlement,
        ))
    return findings


def _bad_debt_offboardings():
    """Tenants offboarded owing money we could NOT recover from their held balance — the only
    figure a human has to chase after closure. Read straight off the completed offboardings."""
    from .models import TenantOffboarding

    rows = (
        TenantOffboarding.objects.filter(
            state=TenantOffboarding.State.COMPLETED, residual_owed__gt=0
        )
        .select_related("operator")
        .order_by("-residual_owed")
    )
    findings = []
    for ob in rows:
        op = ob.operator
        if op is None or op.is_demo or op.is_platform_owned:
            continue
        findings.append(_finding(
            op, "offboarding_bad_debt", "high",
            f"Offboarded still owing KES {ob.residual_owed:,.0f} (unrecovered)",
            residual_owed=str(ob.residual_owed), fees_recovered=str(ob.fees_recovered),
            closed_at=ob.resolved_at.isoformat() if ob.resolved_at else None,
        ))
    return findings


def risk_signals(*, days: int = 30) -> dict:
    """All current risk findings across real tenants, most severe first. Read-only."""
    now = timezone.now()
    findings = (
        _collection_spikes(now)
        + _duplicate_identity()
        + _reactivation_cycling(now)
        + _large_payouts(now)
        + _bad_debt_offboardings()
    )
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"as_of": now.isoformat(), "counts": counts, "findings": findings}
