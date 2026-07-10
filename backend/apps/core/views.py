from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.notifications.models import Campaign
from apps.ops.models import Equipment, Lead, Ticket
from apps.payments.models import Transaction
from apps.plans.models import Plan
from apps.provisioning.models import Router, Session
from apps.vouchers.models import Voucher


def _scoped(qs, operator):
    return qs.filter(operator=operator) if operator is not None else qs


class NavCountsView(APIView):
    """Live badge counts for the admin sidebar, scoped to the tenant."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.core.tenancy import request_operator

        op = request_operator(request)
        users = User.objects.filter(is_staff=False)
        if op is not None:
            users = users.filter(
                Q(operator=op) | Q(transactions__operator=op) | Q(sessions__operator=op)
            ).distinct()
        return Response(
            {
                "active_users": _scoped(
                    Session.objects.filter(status=Session.Status.ACTIVE), op
                ).count(),
                "users": users.count(),
                "tickets": _scoped(
                    Ticket.objects.filter(status__in=Ticket.OPEN_STATUSES), op
                ).count(),
                "leads": _scoped(Lead.objects.filter(status=Lead.Status.NEW), op).count(),
                "packages": _scoped(Plan.objects.filter(is_active=True), op).count(),
                "vouchers": _scoped(
                    Voucher.objects.filter(status=Voucher.Status.UNUSED), op
                ).count(),
                "campaigns": _scoped(Campaign.objects.all(), op).count(),
                "mikrotik": _scoped(Router.objects.filter(is_active=True), op).count(),
                "equipment": _scoped(
                    Equipment.objects.exclude(status=Equipment.Status.RETIRED), op
                ).count(),
            }
        )


class DashboardStatsView(APIView):
    """KPIs + chart series for the operator dashboard. One round trip, everything
    a WISP owner needs to run the business day-to-day."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.core.tenancy import request_operator

        op = request_operator(request)
        now = timezone.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today.replace(day=1)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        paid = _scoped(
            Transaction.objects.filter(status__in=Transaction.SUCCESS_STATUSES), op
        )
        paid_month = paid.filter(callback_received_at__gte=month_start)

        # -- KPIs ----------------------------------------------------------
        revenue_month = paid_month.aggregate(v=Sum("amount"))["v"] or 0
        revenue_prev_month = (
            paid.filter(
                callback_received_at__gte=prev_month_start,
                callback_received_at__lt=month_start,
            ).aggregate(v=Sum("amount"))["v"]
            or 0
        )
        finished_7d = _scoped(
            Transaction.objects.filter(
                created_at__gte=d7, status__in=Transaction.TERMINAL_STATUSES
            ),
            op,
        )
        finished_7d_count = finished_7d.count()
        success_7d_count = finished_7d.filter(
            status__in=Transaction.SUCCESS_STATUSES
        ).count()
        paying_users_month = (
            paid_month.exclude(user=None).values("user").distinct().count()
        )

        kpis = {
            "revenue_today": paid.filter(callback_received_at__gte=today).aggregate(
                v=Sum("amount")
            )["v"]
            or 0,
            "revenue_7d": paid.filter(callback_received_at__gte=d7).aggregate(
                v=Sum("amount")
            )["v"]
            or 0,
            "revenue_month": revenue_month,
            "revenue_prev_month": revenue_prev_month,
            "transactions_today": paid.filter(callback_received_at__gte=today).count(),
            "failed_today": _scoped(
                Transaction.objects.filter(
                    status__in=[Transaction.Status.FAILED, Transaction.Status.TIMEOUT],
                    created_at__gte=today,
                ),
                op,
            ).count(),
            "success_rate_7d": (
                round(100 * success_7d_count / finished_7d_count, 1)
                if finished_7d_count
                else None
            ),
            "active_sessions": _scoped(
                Session.objects.filter(status=Session.Status.ACTIVE), op
            ).count(),
            "sessions_expiring_1h": _scoped(
                Session.objects.filter(
                    status=Session.Status.ACTIVE, expires_at__lte=now + timedelta(hours=1)
                ),
                op,
            ).count(),
            "total_subscribers": (
                User.objects.filter(is_staff=False)
                if op is None
                else User.objects.filter(is_staff=False)
                .filter(Q(operator=op) | Q(transactions__operator=op) | Q(sessions__operator=op))
                .distinct()
            ).count(),
            "new_subscribers_7d": (
                User.objects.filter(is_staff=False, date_joined__gte=d7)
                if op is None
                else User.objects.filter(is_staff=False, date_joined__gte=d7)
                .filter(Q(operator=op) | Q(transactions__operator=op) | Q(sessions__operator=op))
                .distinct()
            ).count(),
            "arpu_month": (
                round(float(revenue_month) / paying_users_month, 2)
                if paying_users_month
                else None
            ),
            "unused_vouchers": _scoped(
                Voucher.objects.filter(status=Voucher.Status.UNUSED), op
            ).count(),
            "vouchers_redeemed_7d": _scoped(
                Voucher.objects.filter(status=Voucher.Status.REDEEMED, redeemed_at__gte=d7),
                op,
            ).count(),
        }

        # -- chart series --------------------------------------------------
        revenue_daily = list(
            paid.filter(callback_received_at__gte=d30)
            .annotate(day=TruncDate("callback_received_at"))
            .values("day")
            .annotate(revenue=Sum("amount"), transactions=Count("id"))
            .order_by("day")
        )

        tx_by_hour_raw = dict(
            paid.filter(callback_received_at__gte=d7)
            .annotate(hour=ExtractHour("callback_received_at"))
            .values_list("hour")
            .annotate(c=Count("id"))
        )
        tx_by_hour = [{"hour": h, "count": tx_by_hour_raw.get(h, 0)} for h in range(24)]

        plan_breakdown = list(
            paid_month.values("plan__name")
            .annotate(count=Count("id"), revenue=Sum("amount"))
            .order_by("-revenue")[:8]
        )

        payment_split = {
            "mpesa": _scoped(
                Session.objects.filter(created_at__gte=d30, transaction__isnull=False), op
            ).count(),
            "voucher": _scoped(
                Session.objects.filter(created_at__gte=d30, voucher__isnull=False), op
            ).count(),
        }

        sessions_daily = list(
            _scoped(
                Session.objects.filter(created_at__gte=timezone.now() - timedelta(days=14)),
                op,
            )
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(sessions=Count("id"))
            .order_by("day")
        )

        routers = list(
            _scoped(Router.objects.filter(is_active=True), op).annotate(
                active_sessions=Count(
                    "sessions", filter=Q(sessions__status=Session.Status.ACTIVE)
                )
            ).values("id", "name", "status", "last_seen_at", "active_sessions")
        )

        return Response(
            {
                "kpis": kpis,
                "revenue_daily": revenue_daily,
                "tx_by_hour": tx_by_hour,
                "plan_breakdown": plan_breakdown,
                "payment_split": payment_split,
                "sessions_daily": sessions_daily,
                "routers": routers,
                "generated_at": now.isoformat(),
            }
        )
