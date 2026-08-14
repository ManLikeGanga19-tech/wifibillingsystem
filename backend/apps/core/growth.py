"""Platform growth analytics — how the WIFI.OS business itself is trending.

MRR here is the platform's RECURRING fee revenue (commission + base + PPPoE per-user; the
one-off setup fee is excluded), summed per tenant per month across both fee ledgers. Movement
diffs each tenant month-over-month into the classic SaaS buckets, and tenant churn falls out
of the same pass (a tenant that was paying and is now at zero). The DEMO tenant is excluded
everywhere — it earns no real revenue (see [[demo-excluded-from-kpis]])."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Operator

MAX_MONTHS = 24


def _month_start(d: datetime) -> datetime:
    local = timezone.localtime(d)
    naive = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _recurring_mrr_by_operator_month(window_start) -> dict[int, dict[str, Decimal]]:
    """{operator_id: {"YYYY-MM": recurring_mrr}} from both fee ledgers, demo excluded.

    Fees are stored NEGATIVE (they debit the ISP), so we negate to get positive revenue."""
    from apps.billing.models import LedgerEntry, PlatformLedgerEntry
    from apps.billing.revenue import RECURRING_REASONS

    out: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    def add(qs):
        rows = (
            qs.filter(created_at__gte=window_start)
            .exclude(operator__is_demo=True)
            .annotate(m=TruncMonth("created_at"))
            .values("operator", "m")
            .annotate(v=Sum("amount"))
        )
        for r in rows:
            if r["operator"] is None or r["m"] is None:
                continue
            out[r["operator"]][r["m"].strftime("%Y-%m")] += -(r["v"] or Decimal("0"))

    add(PlatformLedgerEntry.objects.filter(reason__in=RECURRING_REASONS))
    add(LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION))
    return out


def _live_state_stream() -> dict[int, list[tuple[datetime, bool]]]:
    """{operator_id: [(occurred_at, is_live), ...]} sorted oldest→newest, from the tenant
    lifecycle log. activated/reactivated → live; suspended → not live. This is the source of
    truth for tenant churn — an actual transition, not "their MRR happened to hit zero"."""
    from .models import TenantLifecycleEvent

    LIVE = {TenantLifecycleEvent.Event.ACTIVATED, TenantLifecycleEvent.Event.REACTIVATED}
    stream: dict[int, list[tuple[datetime, bool]]] = defaultdict(list)
    rows = (
        TenantLifecycleEvent.objects.filter(operator__isnull=False)
        .order_by("occurred_at")
        .values_list("operator_id", "event", "occurred_at")
    )
    for op_id, event, when in rows:
        stream[op_id].append((when, event in LIVE))
    return stream


def _live_at(events: list[tuple[datetime, bool]], instant: datetime) -> bool:
    """Was this tenant live at `instant`? = the live-ness of its last event at or before then
    (never activated → not live). Events are pre-sorted oldest→newest."""
    live = False
    for when, is_live in events:
        if when <= instant:
            live = is_live
        else:
            break
    return live


def _status_churn(windows: list[tuple[datetime, datetime]]) -> list[dict]:
    """Precise, status-based tenant churn for each reported month, given its [start, end)
    window (the month's own span — the newest month's end is `now`, so a mid-month
    suspension counts the moment it happens).

    Compares each tenant's LIVE state at the window start vs its end (derived from real
    activation/suspension events), so a tenant that merely skipped a billing month is NOT
    counted as churn — only one that actually went from live to suspended is. Independent of
    MRR timing on purpose. Returns one dict per window (newest last)."""
    stream = _live_state_stream()
    out = []
    for start, end in windows:
        active_start = churned = activated = 0
        for events in stream.values():
            was = _live_at(events, start)
            now_ = _live_at(events, end)
            if was:
                active_start += 1
                if not now_:
                    churned += 1
            elif now_:
                activated += 1
        out.append({
            "active_tenants": active_start,
            "activated_tenants": activated,
            "churned_tenants": churned,
            "tenant_churn_rate": round(churned / active_start, 4) if active_start else None,
        })
    return out


def mrr_movement(*, months: int = 6) -> dict:
    """Per-month MRR waterfall + precise tenant churn for the last `months` months (newest
    last).

    The money buckets (new/expansion/contraction/churned MRR) are derived from the fee
    ledgers. Tenant COUNT churn is separate and precise: it comes from real
    activation/suspension events (see _status_churn), so a billing-timing gap no longer masks
    as a lost ISP."""
    months = max(1, min(months, MAX_MONTHS))
    now = timezone.now()

    # months+1 month-starts: the extra oldest one is the baseline the first reported month
    # diffs against, so it isn't reported itself.
    starts = [_month_start(now)]
    for _ in range(months):
        starts.append(_month_start(starts[-1] - timedelta(days=1)))
    starts.reverse()  # oldest .. newest, length months + 1
    keys = [s.strftime("%Y-%m") for s in starts]

    by_op = _recurring_mrr_by_operator_month(starts[0])
    # Churn window for reported month keys[i] is its OWN span [starts[i], starts[i+1]); the
    # newest month has no next start yet, so it runs to `now` (a partial, live month).
    windows = [(starts[i], starts[i + 1] if i + 1 < len(starts) else now)
               for i in range(1, len(starts))]
    churn = _status_churn(windows)  # aligned 1:1 with the reported months below

    series = []
    for i in range(1, len(keys)):
        prev_k, cur_k = keys[i - 1], keys[i]
        new = expansion = contraction = churned = Decimal("0")
        mrr_total = Decimal("0")
        new_t = 0
        for series_by_month in by_op.values():
            prev = series_by_month.get(prev_k, Decimal("0"))
            cur = series_by_month.get(cur_k, Decimal("0"))
            mrr_total += cur
            if prev == 0 and cur > 0:
                new += cur
                new_t += 1
            elif prev > 0 and cur == 0:
                churned += prev
            elif cur > prev:
                expansion += cur - prev
            elif cur < prev:
                contraction += prev - cur
        series.append({
            "month": cur_k,
            "mrr": mrr_total,
            "new": new,
            "expansion": expansion,
            "contraction": contraction,
            "churned": churned,
            "net": new + expansion - contraction - churned,
            "new_tenants": new_t,
            # precise, status-based tenant counts (NOT the MRR heuristic)
            **churn[i - 1],
        })

    return {
        "as_of": now.isoformat(),
        "months": series,
        "movers": _top_movers(by_op, keys[-2], keys[-1]),
    }


def _top_movers(by_op, prev_k, cur_k, limit=8) -> list[dict]:
    """The biggest MRR changes in the newest month, with the tenant's name and bucket."""
    moves = []
    for op_id, series_by_month in by_op.items():
        prev = series_by_month.get(prev_k, Decimal("0"))
        cur = series_by_month.get(cur_k, Decimal("0"))
        delta = cur - prev
        if delta == 0:
            continue
        if prev == 0:
            bucket = "new"
        elif cur == 0:
            bucket = "churned"
        elif cur > prev:
            bucket = "expansion"
        else:
            bucket = "contraction"
        moves.append({"operator": op_id, "delta": delta, "mrr": cur, "bucket": bucket})

    moves.sort(key=lambda m: abs(m["delta"]), reverse=True)
    moves = moves[:limit]
    names = dict(
        Operator.objects.filter(id__in=[m["operator"] for m in moves]).values_list("id", "name")
    )
    for m in moves:
        m["name"] = names.get(m["operator"], "")
    return moves


# ---- onboarding funnel -------------------------------------------------------------------

MAX_FUNNEL_DAYS = 730
STALE_PENDING_DAYS = 7     # signed up this long ago and STILL not activated = stuck
STALE_NO_PAY_DAYS = 14     # activated this long ago and STILL no collection = stuck


def _median_days(deltas: list[float]) -> float | None:
    if not deltas:
        return None
    s = sorted(deltas)
    n = len(s)
    mid = n // 2
    med = s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
    return round(med, 1)


def onboarding_funnel(*, days: int = 90) -> dict:
    """Where do new ISPs stall between signing up and actually earning?

    A cohort funnel over operators that SIGNED UP in the last `days` (0 = all-time), demo
    excluded. Four milestones, each a strict prerequisite of the next in practice:
    signed up → activated (money gate opened) → settlement verified (cleared to be paid out)
    → first payment (a real collection landed). Plus median time-to-activate /
    time-to-first-payment, and who is stuck RIGHT NOW so support has a call list."""
    from apps.payments.models import C2BPayment, Transaction

    days = max(0, min(days, MAX_FUNNEL_DAYS))
    now = timezone.now()

    cohort = Operator.objects.exclude(is_demo=True).exclude(is_platform_owned=True)
    if days:
        cohort = cohort.filter(created_at__gte=now - timedelta(days=days))
    rows = list(cohort.values("id", "created_at", "approved_at", "settlement_verified_at"))
    ids = [r["id"] for r in rows]

    # First real collection per operator = earliest successful STK txn OR matched C2B payment.
    first_pay: dict[int, datetime] = {}

    def _note(op_id, when):
        if op_id in ids and (op_id not in first_pay or when < first_pay[op_id]):
            first_pay[op_id] = when

    for op_id, when in (
        Transaction.objects.filter(
            operator_id__in=ids, status__in=Transaction.SUCCESS_STATUSES
        ).values_list("operator_id", "created_at")
    ):
        _note(op_id, when)
    for op_id, when in (
        C2BPayment.objects.filter(
            operator_id__in=ids, status=C2BPayment.Status.MATCHED
        ).values_list("operator_id", "received_at")
    ):
        _note(op_id, when)

    signed = activated = verified = paid = 0
    to_activate: list[float] = []
    to_pay: list[float] = []
    stuck_pending = stuck_no_pay = 0
    DAY = 86400.0

    for r in rows:
        signed += 1
        op_id = r["id"]
        appr, ver, pay = r["approved_at"], r["settlement_verified_at"], first_pay.get(op_id)
        if appr:
            activated += 1
            to_activate.append((appr - r["created_at"]).total_seconds() / DAY)
        if ver:
            verified += 1
        if pay:
            paid += 1
            if appr:
                to_pay.append((pay - appr).total_seconds() / DAY)
        # stuck RIGHT NOW (actionable, not historical)
        if not appr and (now - r["created_at"]).days >= STALE_PENDING_DAYS:
            stuck_pending += 1
        elif appr and not pay and (now - appr).days >= STALE_NO_PAY_DAYS:
            stuck_no_pay += 1

    def stage(key, label, count, prev):
        return {
            "key": key,
            "label": label,
            "count": count,
            "pct": round(count / signed, 4) if signed else None,
            "drop_from_prev": max(0, prev - count) if prev is not None else 0,
        }

    stages = [
        stage("signed_up", "Signed up", signed, None),
        stage("activated", "Activated", activated, signed),
        stage("settlement_verified", "Settlement verified", verified, activated),
        stage("first_payment", "First payment", paid, verified),
    ]

    return {
        "as_of": now.isoformat(),
        "window_days": days or None,  # None = all-time
        "cohort_size": signed,
        "stages": stages,
        "median_days_to_activate": _median_days(to_activate),
        "median_days_to_first_payment": _median_days(to_pay),
        "stuck": {
            "pending_over_7d": stuck_pending,
            "activated_no_payment_over_14d": stuck_no_pay,
        },
    }
