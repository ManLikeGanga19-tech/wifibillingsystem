from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from apps.core.services import get_default_operator

from .models import Equipment, Expense, Lead, Ticket
from .serializers import EquipmentSerializer, ExpenseSerializer, LeadSerializer, TicketSerializer


class OperatorScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]

    def perform_create(self, serializer):
        extra = {"operator": get_default_operator()}
        if hasattr(serializer.Meta.model, "created_by"):
            extra["created_by"] = self.request.user
        serializer.save(**extra)


class TicketViewSet(OperatorScopedViewSet):
    serializer_class = TicketSerializer
    queryset = Ticket.objects.select_related("subscriber").order_by("-created_at")


class LeadViewSet(OperatorScopedViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.order_by("-created_at")


class ExpenseViewSet(OperatorScopedViewSet):
    serializer_class = ExpenseSerializer
    queryset = Expense.objects.select_related("router").order_by("-date", "-created_at")


class EquipmentViewSet(OperatorScopedViewSet):
    serializer_class = EquipmentSerializer
    queryset = Equipment.objects.select_related("router").order_by("-created_at")
