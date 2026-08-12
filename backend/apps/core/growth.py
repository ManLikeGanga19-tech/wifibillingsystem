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


def mrr_movement(*, months: int = 6) -> dict:
    """Per-month MRR waterfall + tenant churn for the last `months` months (newest last)."""
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

    series = []
    for i in range(1, len(keys)):
        prev_k, cur_k = keys[i - 1], keys[i]
        new = expansion = contraction = churned = Decimal("0")
        mrr_total = Decimal("0")
        new_t = churned_t = paying_start = 0
        for series_by_month in by_op.values():
            prev = series_by_month.get(prev_k, Decimal("0"))
            cur = series_by_month.get(cur_k, Decimal("0"))
            mrr_total += cur
            if prev > 0:
                paying_start += 1
            if prev == 0 and cur > 0:
                new += cur
                new_t += 1
            elif prev > 0 and cur == 0:
                churned += prev
                churned_t += 1
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
            "churned_tenants": churned_t,
            "tenant_churn_rate": (
                round(churned_t / paying_start, 4) if paying_start else None
            ),
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
