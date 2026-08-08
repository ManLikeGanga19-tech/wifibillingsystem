"""Churn & retention analytics for fixed-line (PPPoE) subscribers.

Point-in-time status can only say who is active NOW. Churn is a question about MOVEMENT over
time — "how many left in July", "what's my monthly churn rate" — so every number here is
derived from the ClientLifecycleEvent log, the dated record of every activate / suspend /
restore / cancel. All queries are operator-scoped by the caller passing the acting tenant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from django.utils import timezone

from .models import Client, ClientLifecycleEvent

# A client counts toward the customer base while it is being served — active, or suspended
# (overdue but not yet given up on). Cancelled/pending are not part of the base.
_SERVED_STATUSES = (Client.Status.ACTIVE, Client.Status.SUSPENDED)

MAX_MONTHS = 24


def _month_start(d: datetime) -> datetime:
    """First instant of d's month, in the project timezone."""
    local = timezone.localtime(d)
    naive = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _add_month(d: datetime) -> datetime:
    """First instant of the month AFTER d's month."""
    year, month = d.year, d.month
    return d.replace(year=year + 1, month=1) if month == 12 else d.replace(month=month + 1)


def served_count_at(operator, when: datetime) -> int:
    """How many clients were in service (active or suspended) at the instant `when`.

    Reconstructed from the log: each client's most recent event strictly before `when`
    tells us the state it was in then. Deleted clients (client_id NULL) are excluded — their
    row is gone, and a served client is essentially never hard-deleted, so this is exact in
    practice and only ever slightly conservative at the edge."""
    latest_states = (
        ClientLifecycleEvent.objects.filter(
            operator=operator, occurred_at__lt=when, client_id__isnull=False
        )
        .order_by("client_id", "-occurred_at")
        .distinct("client_id")
        .values_list("to_status", flat=True)
    )
    return sum(1 for status in latest_states if status in _SERVED_STATUSES)


@dataclass
class MonthChurn:
    month: str  # "YYYY-MM"
    active_start: int  # customer base at the first of the month (active + suspended)
    new: int  # first-time activations
    reactivated: int  # churned customers won back
    suspended: int  # lapses (may still recover)
    restored: int  # recoveries (paid up)
    churned: int  # cancellations — the ones who left
    net: int  # new + reactivated - churned
    churn_rate: float | None  # churned / active_start, or None when the base was empty


def _counts_in(operator, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        ClientLifecycleEvent.objects.filter(
            operator=operator, occurred_at__gte=start, occurred_at__lt=end
        )
        .values_list("event")
        .order_by()
    )
    tally: dict[str, int] = {}
    for (event,) in rows:
        tally[event] = tally.get(event, 0) + 1
    return tally


def churn_summary(operator, *, months: int = 6) -> dict:
    """Per-month subscriber movement and churn rate for the last `months` months, plus the
    current standing. Newest month last, so a chart reads left-to-right in time."""
    months = max(1, min(months, MAX_MONTHS))
    now = timezone.now()

    current_start = _month_start(now)
    starts = [current_start]
    for _ in range(months - 1):
        starts.append(_month_start(starts[-1] - timezone.timedelta(days=1)))
    starts.reverse()  # oldest -> newest

    E = ClientLifecycleEvent.Event
    series: list[MonthChurn] = []
    for start in starts:
        end = _add_month(start)
        c = _counts_in(operator, start, end)
        new = c.get(E.ACTIVATED, 0)
        reactivated = c.get(E.REACTIVATED, 0)
        churned = c.get(E.CANCELLED, 0)
        base = served_count_at(operator, start)
        series.append(
            MonthChurn(
                month=timezone.localtime(start).strftime("%Y-%m"),
                active_start=base,
                new=new,
                reactivated=reactivated,
                suspended=c.get(E.SUSPENDED, 0),
                restored=c.get(E.RESTORED, 0),
                churned=churned,
                net=new + reactivated - churned,
                churn_rate=round(churned / base, 4) if base else None,
            )
        )

    standing = {
        s.value: Client.objects.filter(operator=operator, status=s).count()
        for s in Client.Status
    }
    return {
        "as_of": now.isoformat(),
        "standing": standing,
        "months": [asdict(m) for m in series],
    }
