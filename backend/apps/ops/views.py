from datetime import datetime

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import (
    FINANCE_VIEW,
    LEADS_VIEW,
    LEADS_WRITE,
    NETWORK_WRITE,
    TICKETS_ASSIGN,
    TICKETS_VIEW,
    TICKETS_WORK,
)
from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
from apps.core.services import audit
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
    read_capability = TICKETS_VIEW
    write_capability = TICKETS_WORK          # Owner/Admin/Care/Technician may all work a ticket

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # LAYER B row-scoping: a technician sees ONLY the tickets assigned to them. The proxy for
        # "technician" is "can view but cannot assign" — the only tenant role in that shape.
        # Platform staff bypass capabilities and keep the full support view.
        if (not user.is_platform_staff
                and user.has_capability(TICKETS_VIEW)
                and not user.has_capability(TICKETS_ASSIGN)):
            qs = qs.filter(assigned_to=user)
        return qs

    def _strip_assignment(self, serializer):
        # Handing a ticket to a technician is tickets.assign (Care/Admin/Owner). A technician
        # working their own ticket may change its status but never re-route it — drop assigned_to.
        user = self.request.user
        if "assigned_to" in serializer.validated_data and not user.has_capability(TICKETS_ASSIGN):
            serializer.validated_data.pop("assigned_to")

    def perform_create(self, serializer):
        self._strip_assignment(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._strip_assignment(serializer)
        super().perform_update(serializer)

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Assign this ticket to the nearest live technician")
    # url_path/url_name "dispatch" for a clean /tickets/<id>/dispatch/ — but the METHOD can't be
    # named dispatch (that's the view's own request-routing method), so it's dispatch_nearest.
    @action(detail=True, methods=["post"], url_path="dispatch", url_name="dispatch")
    def dispatch_nearest(self, request, pk=None):
        """Send the CLOSEST sharing technician to this fault: given the fault's coordinate, pick
        the nearest live tech and assign them the ticket. Assigning is tickets.assign (a technician
        can work their own ticket but can't route work), so the dispatch action requires it even
        though the viewset's general write is tickets.work."""
        if not request.user.has_capability(TICKETS_ASSIGN):
            raise PermissionDenied("You don't have permission to assign tickets.")
        from apps.fleet.services import nearest_technicians

        ticket = self.get_object()
        try:
            lat, lng = float(request.data.get("lat")), float(request.data.get("lng"))
        except (TypeError, ValueError):
            return Response({"detail": "Provide the fault location (lat, lng)."},
                            status=status.HTTP_400_BAD_REQUEST)
        ranked = nearest_technicians(self.get_operator(), lat, lng, live_only=True)
        if not ranked:
            return Response(
                {"detail": "No technician is sharing their location right now."},
                status=status.HTTP_409_CONFLICT,
            )
        ping, dist = ranked[0]
        ticket.assigned_to = ping.technician
        ticket.save(update_fields=["assigned_to"])
        audit("ticket_dispatched", operator=self.get_operator(), actor=request.user, target=ticket,
              technician=ping.technician_id, distance_km=round(dist, 2))
        return Response({
            "detail": f"Dispatched to {ping.technician.name or ping.technician.phone}.",
            "technician_id": ping.technician_id,
            "technician_name": ping.technician.name,
            "distance_km": round(dist, 2),
        })


class LeadViewSet(StatusFilterMixin, TenantModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.order_by("-created_at")
    read_capability = LEADS_VIEW             # technician: read-only (map layer)
    write_capability = LEADS_WRITE           # the CRM — Care/Admin/Owner


class ExpenseViewSet(TenantModelViewSet):
    serializer_class = ExpenseSerializer
    queryset = Expense.objects.select_related("router").order_by("-date", "-created_at")
    read_capability = FINANCE_VIEW           # the books — Owner/Admin
    write_capability = FINANCE_VIEW


class EquipmentViewSet(StatusFilterMixin, TenantModelViewSet):
    serializer_class = EquipmentSerializer
    queryset = Equipment.objects.select_related("router").order_by("-created_at")
    read_capability = NETWORK_WRITE          # CPE / plant inventory — Owner/Admin/Technician
    write_capability = NETWORK_WRITE


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
