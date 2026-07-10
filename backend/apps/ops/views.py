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
