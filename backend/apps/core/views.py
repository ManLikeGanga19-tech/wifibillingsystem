from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import Transaction
from apps.provisioning.models import Router, Session
from apps.vouchers.models import Voucher


class DashboardStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today.replace(day=1)
        success = Transaction.objects.filter(status=Transaction.Status.SUCCESS)
        return Response(
            {
                "revenue_today": success.filter(callback_received_at__gte=today).aggregate(
                    v=Sum("amount")
                )["v"]
                or 0,
                "revenue_month": success.filter(callback_received_at__gte=month_start).aggregate(
                    v=Sum("amount")
                )["v"]
                or 0,
                "transactions_today": success.filter(callback_received_at__gte=today).count(),
                "active_sessions": Session.objects.filter(status=Session.Status.ACTIVE).count(),
                "sessions_expiring_1h": Session.objects.filter(
                    status=Session.Status.ACTIVE, expires_at__lte=now + timedelta(hours=1)
                ).count(),
                "unused_vouchers": Voucher.objects.filter(status=Voucher.Status.UNUSED).count(),
                "routers": list(
                    Router.objects.filter(is_active=True).values("name", "status", "last_seen_at")
                ),
                "failed_transactions_today": Transaction.objects.filter(
                    status__in=[Transaction.Status.FAILED, Transaction.Status.TIMEOUT],
                    created_at__gte=today,
                ).count(),
                "plan_breakdown": list(
                    success.filter(callback_received_at__gte=month_start)
                    .values("plan__name")
                    .annotate(count=Count("id"), revenue=Sum("amount"))
                    .order_by("-revenue")
                ),
            }
        )
