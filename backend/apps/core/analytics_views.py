"""Platform analytics — the numbers Danamo runs the business on.

Everything here is CROSS-TENANT by design and platform-staff only. The guiding
question for each endpoint is one a founder actually asks:

  - KPIs        : "how is the business doing right now?"
  - Timeseries  : "which way is it trending?"
  - Tenant P&L  : "which ISPs actually make me money after the rails take their cut?"
  - Search      : "find me this payment / phone / account, across every ISP"
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import LedgerEntry, Payout, Settlement
from apps.payments.models import C2BPayment, Transaction

from .models import Operator
from .permissions import IsPlatformStaff
from .schema import OBJECT_RESPONSE

# Ledger types that are platform REVENUE (stored negative — they debit the ISP)
EARNING_TYPES = [
    LedgerEntry.Type.COMMISSION,
    LedgerEntry.Type.BASE_FEE,
    LedgerEntry.Type.PPPOE_FEE,
    LedgerEntry.Type.SETUP_FEE,
]
# Recurring subscription revenue (what MRR actually means — excludes one-off setup)
RECURRING_TYPES = [
    LedgerEntry.Type.COMMISSION,
    LedgerEntry.Type.BASE_FEE,
    LedgerEntry.Type.PPPOE_FEE,
]

_MONEY = DecimalField(max_digits=14, decimal_places=2)


def _sum(qs, field="amount") -> Decimal:
    return qs.aggregate(v=Coalesce(Sum(field), Value(Decimal("0")), output_field=_MONEY))["v"]


def _month_start(now=None):
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@extend_schema(responses=OBJECT_RESPONSE, summary="Platform KPIs (all ISPs)")
class PlatformKpisView(APIView):
    """The Command Center's headline numbers, plus the alerts that need a human."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate()
        month_start = _month_start(now)

        # --- Revenue ---------------------------------------------------------
        # Fees now live in TWO ledgers (aggregator commission withheld in the wallet;
        # everything else accrued on the platform account). billing.revenue spans both, so
        # moving a fee between them can never silently drop it from MRR.
        from apps.billing.revenue import platform_earnings, platform_earnings_by_stream

        mrr = platform_earnings(start=month_start, recurring_only=True)
        earnings_month = platform_earnings(start=month_start)
        by_stream = platform_earnings_by_stream(start=month_start)

        # --- Costs we absorb --------------------------------------------------
        costs_month = (
            _sum(
                Transaction.objects.filter(
                    status__in=Transaction.SUCCESS_STATUSES,
                    callback_received_at__gte=month_start,
                ),
                "platform_cost",
            )
            + _sum(
                C2BPayment.objects.filter(received_at__gte=month_start), "platform_cost"
            )
            + _sum(
                Payout.objects.filter(
                    status=Payout.Status.PAID, processed_at__gte=month_start
                ),
                "platform_cost",
            )
        )

        gross_volume_month = _sum(
            LedgerEntry.objects.filter(
                entry_type=LedgerEntry.Type.SALE, created_at__gte=month_start
            )
        )
        # Float = every ISP wallet balance summed = what we owe them, and therefore what we
        # must actually be HOLDING. Sales settled straight into an ISP's own gateway never
        # touched our account, so counting them here would inflate our float by money that
        # was never ours to hold — and this number is what tells us we can cover a payout
        # run.
        float_held = _sum(LedgerEntry.objects.filter(settlement=Settlement.PLATFORM))

        # --- Alerts (things a human must act on) ------------------------------
        pending_approvals = Operator.objects.filter(status=Operator.Status.PENDING).count()
        trials_expiring = Operator.objects.filter(
            status=Operator.Status.ACTIVE,
            trial_ends_at__isnull=False,
            trial_ends_at__gte=today,
            trial_ends_at__lte=today + timedelta(days=7),
        ).count()
        pending_payouts = Payout.objects.filter(status=Payout.Status.REQUESTED)
        stale_payouts = pending_payouts.filter(
            created_at__lte=now - timedelta(days=2)
        ).count()
        unmatched_c2b = C2BPayment.objects.filter(
            status=C2BPayment.Status.UNMATCHED
        ).count()

        from apps.provisioning.models import Router, Session

        routers = Router.objects.filter(is_active=True)
        routers_total = routers.count()
        routers_online = routers.filter(status=Router.Status.ONLINE).count()

        return Response(
            {
                "scope": "all_isps",
                # Revenue
                "mrr": mrr,
                "arr": (mrr * 12).quantize(Decimal("0.01")),
                "earnings_month": earnings_month,
                "revenue_by_stream": by_stream,
                # True margin
                "transaction_costs_month": costs_month,
                "net_margin_month": earnings_month - costs_month,
                "margin_pct": (
                    round(100 * float(earnings_month - costs_month) / float(earnings_month), 1)
                    if earnings_month > 0
                    else 0.0
                ),
                # Volume + custody
                "gross_volume_month": gross_volume_month,
                "float_held": float_held,
                # Tenants
                "tenants_active": Operator.objects.filter(
                    status=Operator.Status.ACTIVE
                ).count(),
                "tenants_total": Operator.objects.count(),
                "new_tenants_30d": Operator.objects.filter(
                    created_at__gte=now - timedelta(days=30)
                ).count(),
                # Fleet
                "routers_online": routers_online,
                "routers_total": routers_total,
                "active_sessions": Session.objects.filter(
                    status=Session.Status.ACTIVE
                ).count(),
                # Alerts — each is a number that should be zero
                "alerts": {
                    "pending_approvals": pending_approvals,
                    "trials_expiring_7d": trials_expiring,
                    "payouts_pending": pending_payouts.count(),
                    "payouts_stale_2d": stale_payouts,
                    "unmatched_payments": unmatched_c2b,
                    "routers_offline": routers_total - routers_online,
                },
            }
        )


@extend_schema(responses=OBJECT_RESPONSE, summary="Daily trend series (all ISPs)")
class PlatformTimeseriesView(APIView):
    """Daily buckets for the trend graphs. ?days=30 (default), max 365."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 30)), 7), 365)
        except ValueError:
            days = 30
        start = timezone.now() - timedelta(days=days)

        def daily(qs, date_field, value_field="amount", negate=False):
            rows = (
                qs.filter(**{f"{date_field}__gte": start})
                .annotate(d=TruncDate(date_field))
                .values("d")
                .annotate(v=Coalesce(Sum(value_field), Value(Decimal("0")), output_field=_MONEY))
            )
            out = {}
            for r in rows:
                if r["d"] is None:
                    continue
                out[r["d"].isoformat()] = -r["v"] if negate else r["v"]
            return out

        from apps.billing.models import PlatformLedgerEntry
        from apps.billing.revenue import PLATFORM_REVENUE_REASONS

        sales = daily(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.SALE), "created_at"
        )
        # Earnings span both ledgers now: aggregator commission withheld in the wallet PLUS
        # every fee accrued on the platform account. Merge the two daily series so no day
        # under-reports.
        earn_wallet = daily(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION),
            "created_at", negate=True,
        )
        earn_platform = daily(
            PlatformLedgerEntry.objects.filter(reason__in=PLATFORM_REVENUE_REASONS),
            "created_at", negate=True,
        )
        earnings = {
            d: earn_wallet.get(d, Decimal("0")) + earn_platform.get(d, Decimal("0"))
            for d in set(earn_wallet) | set(earn_platform)
        }
        tx_costs = daily(
            Transaction.objects.filter(status__in=Transaction.SUCCESS_STATUSES),
            "callback_received_at",
            "platform_cost",
        )
        c2b_costs = daily(C2BPayment.objects.all(), "received_at", "platform_cost")
        signups = (
            Operator.objects.filter(created_at__gte=start)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(n=Count("id"))
        )
        signup_map = {r["d"].isoformat(): r["n"] for r in signups if r["d"]}

        # Emit a dense series — a gap day must render as 0, not vanish
        series = []
        day0 = timezone.localdate() - timedelta(days=days - 1)
        for i in range(days):
            d = (day0 + timedelta(days=i)).isoformat()
            gross = sales.get(d, Decimal("0"))
            earn = earnings.get(d, Decimal("0"))
            cost = tx_costs.get(d, Decimal("0")) + c2b_costs.get(d, Decimal("0"))
            series.append(
                {
                    "date": d,
                    "gross_volume": gross,
                    "earnings": earn,
                    "transaction_costs": cost,
                    "net_margin": earn - cost,
                    "new_tenants": signup_map.get(d, 0),
                }
            )
        return Response({"scope": "all_isps", "days": days, "series": series})


@extend_schema(responses=OBJECT_RESPONSE, summary="Per-ISP profit and loss")
class TenantPnlView(APIView):
    """Per-ISP profitability: what each tenant EARNS us versus what it COSTS us.

    The question no dashboard answered before: after the M-Pesa/bank rails take
    their cut (which Danamo absorbs), which ISPs are actually profitable? A tenant
    with heavy high-value PPPoE collections can generate real revenue and still be
    thin once its collection costs are attributed.
    """

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        rows = []
        operators = Operator.objects.all().order_by("name")

        from apps.billing.models import PlatformLedgerEntry
        from apps.billing.revenue import PLATFORM_REVENUE_REASONS

        # Pre-aggregate per operator to avoid an N+1 storm. Earnings span both ledgers:
        # aggregator commission withheld in the wallet + fees accrued on the platform
        # account. Merge so a per-ISP P&L never under-counts what they earn us.
        earn: dict = {}
        for r in (
            LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION)
            .values("operator")
            .annotate(v=Coalesce(Sum("amount"), Value(Decimal("0")), output_field=_MONEY))
        ):
            earn[r["operator"]] = earn.get(r["operator"], Decimal("0")) - r["v"]
        for r in (
            PlatformLedgerEntry.objects.filter(reason__in=PLATFORM_REVENUE_REASONS)
            .values("operator")
            .annotate(v=Coalesce(Sum("amount"), Value(Decimal("0")), output_field=_MONEY))
        ):
            earn[r["operator"]] = earn.get(r["operator"], Decimal("0")) - r["v"]
        gross = {
            r["operator"]: r["v"]
            for r in LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.SALE)
            .values("operator")
            .annotate(v=Coalesce(Sum("amount"), Value(Decimal("0")), output_field=_MONEY))
        }
        balance = {
            r["operator"]: r["v"]
            for r in LedgerEntry.objects.values("operator").annotate(
                v=Coalesce(Sum("amount"), Value(Decimal("0")), output_field=_MONEY)
            )
        }
        tx_cost = {
            r["operator"]: r["v"]
            for r in Transaction.objects.filter(status__in=Transaction.SUCCESS_STATUSES)
            .values("operator")
            .annotate(
                v=Coalesce(Sum("platform_cost"), Value(Decimal("0")), output_field=_MONEY)
            )
        }
        c2b_cost = {
            r["operator"]: r["v"]
            for r in C2BPayment.objects.filter(operator__isnull=False)
            .values("operator")
            .annotate(
                v=Coalesce(Sum("platform_cost"), Value(Decimal("0")), output_field=_MONEY)
            )
        }
        payout_cost = {
            r["operator"]: r["v"]
            for r in Payout.objects.filter(status=Payout.Status.PAID)
            .values("operator")
            .annotate(
                v=Coalesce(Sum("platform_cost"), Value(Decimal("0")), output_field=_MONEY)
            )
        }

        from apps.pppoe.models import Client

        pppoe_counts = {
            r["operator"]: r["n"]
            for r in Client.objects.filter(status__in=Client.BILLABLE_STATUSES)
            .values("operator")
            .annotate(n=Count("id"))
        }

        zero = Decimal("0")
        for op in operators:
            revenue = earn.get(op.id, zero)
            cost = (
                tx_cost.get(op.id, zero)
                + c2b_cost.get(op.id, zero)
                + payout_cost.get(op.id, zero)
            )
            net = revenue - cost
            rows.append(
                {
                    "id": op.id,
                    "slug": op.slug,
                    "name": op.name,
                    "status": op.status,
                    "is_platform_owned": op.is_platform_owned,
                    "in_trial": op.in_base_fee_trial(),
                    "gross_collected": gross.get(op.id, zero),
                    "revenue": revenue,
                    "transaction_costs": cost,
                    "net_margin": net,
                    "margin_pct": (
                        round(100 * float(net) / float(revenue), 1) if revenue > 0 else 0.0
                    ),
                    "wallet_balance": balance.get(op.id, zero),
                    "pppoe_users": pppoe_counts.get(op.id, 0),
                }
            )
        rows.sort(key=lambda r: r["net_margin"], reverse=True)

        return Response(
            {
                "scope": "all_isps",
                "totals": {
                    "revenue": sum((r["revenue"] for r in rows), zero),
                    "transaction_costs": sum((r["transaction_costs"] for r in rows), zero),
                    "net_margin": sum((r["net_margin"] for r in rows), zero),
                },
                "tenants": rows,
            }
        )


@extend_schema(responses=OBJECT_RESPONSE, summary="Cross-tenant support search")
class PlatformSearchView(APIView):
    """Cross-tenant support search — the tool that means you rarely need to walk
    into an ISP's console at all. Finds a payment / phone / account / router
    across EVERY ISP, and always tells you which tenant it belongs to."""

    permission_classes = [IsPlatformStaff]
    LIMIT = 10

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 3:
            return Response({"q": q, "detail": "Enter at least 3 characters.", "results": {}})

        results = {}

        # ISPs
        results["tenants"] = [
            {"id": o.id, "slug": o.slug, "name": o.name, "status": o.status}
            for o in Operator.objects.filter(
                Q(name__icontains=q) | Q(slug__icontains=q) | Q(contact_phone__icontains=q)
            )[: self.LIMIT]
        ]

        # Hotspot payments (M-Pesa receipt, phone, checkout id)
        results["transactions"] = [
            {
                "id": t.id,
                "tenant": t.operator.slug if t.operator else "",
                "phone": t.phone,
                "amount": t.amount,
                "status": t.status,
                "mpesa_receipt": t.mpesa_receipt,
                "created_at": t.created_at,
            }
            for t in Transaction.objects.select_related("operator")
            .filter(
                Q(mpesa_receipt__iexact=q)
                | Q(phone__icontains=q)
                | Q(checkout_request_id__iexact=q)
            )
            .order_by("-created_at")[: self.LIMIT]
        ]

        # Broadband payments (C2B TransID / account ref / payer msisdn)
        results["c2b_payments"] = [
            {
                "id": p.id,
                "tenant": p.operator.slug if p.operator else "",
                "trans_id": p.trans_id,
                "bill_ref": p.bill_ref,
                "msisdn": p.msisdn,
                "amount": p.amount,
                "status": p.status,
                "received_at": p.received_at,
            }
            for p in C2BPayment.objects.select_related("operator")
            .filter(
                Q(trans_id__iexact=q) | Q(bill_ref__icontains=q) | Q(msisdn__icontains=q)
            )
            .order_by("-received_at")[: self.LIMIT]
        ]

        # Broadband clients (account number, name, phone, pppoe user)
        from apps.pppoe.models import Client

        results["pppoe_clients"] = [
            {
                "id": c.id,
                "tenant": c.operator.slug,
                "account_number": c.account_number,
                "full_name": c.full_name,
                "phone": c.phone,
                "status": c.status,
                "plan": c.plan.name if c.plan_id else "",
            }
            for c in Client.objects.select_related("operator", "plan").filter(
                Q(account_number__icontains=q)
                | Q(full_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(pppoe_username__icontains=q)
            )[: self.LIMIT]
        ]

        # Hotspot customers
        from apps.accounts.models import Subscriber

        results["subscribers"] = [
            {
                "id": s.id,
                "tenant": s.operator.slug,
                "phone": s.phone,
                "name": s.name,
            }
            for s in Subscriber.objects.select_related("operator").filter(
                Q(phone__icontains=q) | Q(name__icontains=q)
            )[: self.LIMIT]
        ]

        # Routers
        from apps.provisioning.models import Router

        results["routers"] = [
            {
                "id": r.id,
                "tenant": r.operator.slug,
                "name": r.name,
                "host": r.management_host,
                "status": r.status,
            }
            for r in Router.objects.select_related("operator").filter(
                Q(name__icontains=q) | Q(management_host__icontains=q)
            )[: self.LIMIT]
        ]

        total = sum(len(v) for v in results.values())
        return Response({"q": q, "total": total, "results": results})
