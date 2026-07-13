"""Reports and exports — what an ISP needs to run the business and do its books.

The dashboard answers "how am I doing right now". This answers "show me March", "which
plan actually earns", and — the one an accountant asks for — "give me the CSV so I can
reconcile against my M-Pesa statement".

Everything here is tenant-scoped by the caller; these functions take an already-resolved
operator and never reach across tenants.
"""

import csv
from datetime import datetime, time, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import StreamingHttpResponse
from django.utils import timezone

from apps.payments.models import C2BPayment, Transaction

from .models import LedgerEntry


def parse_range(request, *, default_days=30):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD -> aware [start, end] datetimes. Missing/garbage
    falls back to the last `default_days`, so a report endpoint never 500s on a typo."""
    tz = timezone.get_current_timezone()

    def _day(value, fallback):
        try:
            d = datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return fallback
        return d

    today = timezone.localdate()
    start_d = _day(request.query_params.get("from"), today - timedelta(days=default_days))
    end_d = _day(request.query_params.get("to"), today)
    start = timezone.make_aware(datetime.combine(start_d, time.min), tz)
    # Inclusive of the end day: through 23:59:59.
    end = timezone.make_aware(datetime.combine(end_d, time.max), tz)
    return start, end


def revenue_summary(operator, start, end) -> dict:
    """Money in over a period: the totals, split by source and by plan, plus a daily
    series for the chart. Reconciled counts as paid — the money arrived."""
    paid = Transaction.objects.filter(
        operator=operator,
        status__in=Transaction.SUCCESS_STATUSES,
        callback_received_at__gte=start,
        callback_received_at__lte=end,
    )
    c2b = C2BPayment.objects.filter(
        operator=operator,
        status=C2BPayment.Status.MATCHED,
        received_at__gte=start,
        received_at__lte=end,
    )

    hotspot_total = paid.aggregate(v=Sum("amount"))["v"] or 0
    pppoe_total = c2b.aggregate(v=Sum("amount"))["v"] or 0

    by_plan = list(
        paid.values("plan__name")
        .annotate(revenue=Sum("amount"), count=Count("id"))
        .order_by("-revenue")
    )

    # Daily series, both sources folded into one per-day figure.
    daily: dict[str, float] = {}
    for row in paid.annotate(d=TruncDate("callback_received_at")).values("d").annotate(
        v=Sum("amount")
    ):
        daily[row["d"].isoformat()] = float(row["v"] or 0)
    for row in c2b.annotate(d=TruncDate("received_at")).values("d").annotate(v=Sum("amount")):
        key = row["d"].isoformat()
        daily[key] = daily.get(key, 0) + float(row["v"] or 0)

    return {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "total": float(hotspot_total) + float(pppoe_total),
        "hotspot_total": float(hotspot_total),
        "pppoe_total": float(pppoe_total),
        "hotspot_count": paid.count(),
        "pppoe_count": c2b.count(),
        "by_plan": [
            {"plan": r["plan__name"], "revenue": float(r["revenue"] or 0), "count": r["count"]}
            for r in by_plan
        ],
        "daily": [{"day": k, "revenue": v} for k, v in sorted(daily.items())],
    }


# ---- CSV exports -------------------------------------------------------------------
#
# Streamed row-by-row (StreamingHttpResponse) so a year of transactions doesn't build a
# giant string in memory before the download starts.


class _Echo:
    """A file-like object whose write() just returns the value, for csv.writer."""

    def write(self, value):
        return value


def _stream_csv(filename, header, rows):
    writer = csv.writer(_Echo())

    def generate():
        yield writer.writerow(header)
        for row in rows:
            yield writer.writerow(row)

    resp = StreamingHttpResponse(generate(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def transactions_csv(operator, start, end):
    qs = (
        Transaction.objects.filter(
            operator=operator, created_at__gte=start, created_at__lte=end
        )
        .select_related("plan")
        .order_by("created_at")
        .iterator()
    )
    header = ["Date", "Phone", "Plan", "Amount", "Status", "M-Pesa receipt", "Checkout ID"]
    rows = (
        [
            timezone.localtime(t.created_at).strftime("%Y-%m-%d %H:%M"),
            t.phone,
            t.plan.name if t.plan_id else "",
            t.amount,
            t.status,
            t.mpesa_receipt,
            t.checkout_request_id or "",
        ]
        for t in qs
    )
    return _stream_csv("hotspot-payments.csv", header, rows)


def pppoe_payments_csv(operator, start, end):
    qs = (
        C2BPayment.objects.filter(
            operator=operator, received_at__gte=start, received_at__lte=end
        )
        .select_related("client")
        .order_by("received_at")
        .iterator()
    )
    header = ["Date", "Account (typed)", "Client", "Paid from", "Amount", "Status", "M-Pesa ref"]
    rows = (
        [
            timezone.localtime(p.received_at).strftime("%Y-%m-%d %H:%M"),
            p.bill_ref,
            p.client.full_name if p.client_id else "",
            p.msisdn,
            p.amount,
            p.status,
            p.trans_id,
        ]
        for p in qs
    )
    return _stream_csv("pppoe-payments.csv", header, rows)


def ledger_csv(operator, start, end):
    qs = (
        LedgerEntry.objects.filter(
            operator=operator, created_at__gte=start, created_at__lte=end
        )
        .order_by("created_at")
        .iterator()
    )
    header = ["Date", "Type", "Amount", "Memo"]
    rows = (
        [
            timezone.localtime(e.created_at).strftime("%Y-%m-%d %H:%M"),
            e.entry_type,
            e.amount,
            e.memo,
        ]
        for e in qs
    )
    return _stream_csv("wallet-ledger.csv", header, rows)
