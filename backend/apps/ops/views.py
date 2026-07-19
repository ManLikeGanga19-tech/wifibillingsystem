from datetime import datetime

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantModelViewSet

from .models import Equipment, Expense, Lead, Ticket
from .serializers import EquipmentSerializer, ExpenseSerializer, LeadSerializer, TicketSerializer


class StatusFilterMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class TicketViewSet(StatusFilterMixin, TenantModelViewSet):
    serializer_class = TicketSerializer
    queryset = Ticket.objects.select_related("subscriber").order_by("-created_at")


class LeadViewSet(StatusFilterMixin, TenantModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.order_by("-created_at")


class ExpenseViewSet(TenantModelViewSet):
    serializer_class = ExpenseSerializer
    queryset = Expense.objects.select_related("router").order_by("-date", "-created_at")


class EquipmentViewSet(StatusFilterMixin, TenantModelViewSet):
    serializer_class = EquipmentSerializer
    queryset = Equipment.objects.select_related("router").order_by("-created_at")


class PlatformFeesView(APIView):
    """The auto side of Expenses: what this ISP paid WIFI.OS (Danamo) in a given month — platform
    fee, commission, PPPoE per-user fee, setup, and SMS. Pulled live from billing so the ISP's
    profit picture includes their platform cost without them keying it in."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    LABELS = {
        "base_fee": "Monthly platform fee",
        "commission": "Commission (direct sales)",
        "pppoe_fee": "PPPoE per-user fee",
        "setup_fee": "Setup fee",
        "sms": "SMS sent",
    }

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's WIFI.OS fees for a month")
    def get(self, request):
        from django.utils import timezone

        from apps.billing.platform_account import platform_charges

        raw = request.query_params.get("month") or timezone.localdate().strftime("%Y-%m")
        try:
            first = datetime.strptime(raw, "%Y-%m").date().replace(day=1)
        except ValueError:
            first = timezone.localdate().replace(day=1)
        # First day of the next month, without dateutil.
        nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 else \
            first.replace(month=first.month + 1)
        start = timezone.make_aware(datetime.combine(first, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(nxt, datetime.min.time()))

        data = platform_charges(acting_tenant(request), start=start, end=end)
        lines = [
            {"key": key, "label": self.LABELS.get(key, key), "amount": str(amount)}
            for key, amount in data["by_reason"].items()
        ]
        return Response(
            {"month": first.strftime("%Y-%m"), "total": str(data["total"]), "lines": lines}
        )
