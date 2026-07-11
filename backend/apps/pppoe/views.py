from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.public import PublicAPIView
from apps.core.schema import OBJECT_RESPONSE
from apps.core.viewsets import TenantModelViewSet, TenantReadOnlyViewSet
from apps.provisioning.adapters import ProvisioningError, get_adapter

from .models import AccessPoint, Client, Invoice, ServicePlan, Tower
from .serializers import (
    AccessPointSerializer,
    ClientSerializer,
    InvoiceSerializer,
    ServicePlanSerializer,
    TowerSerializer,
)
from .services import create_client, provision_client, restore_client, suspend_client


class ServicePlanViewSet(TenantModelViewSet):
    serializer_class = ServicePlanSerializer
    queryset = ServicePlan.objects.all()


class TowerViewSet(TenantModelViewSet):
    serializer_class = TowerSerializer
    queryset = Tower.objects.all()

    def get_queryset(self):
        # super() applies the tenant filter (TenantScopedMixin) — never bypass it
        return super().get_queryset().annotate(
            access_point_count=Count("access_points")
        ).order_by("name")


class AccessPointViewSet(TenantModelViewSet):
    serializer_class = AccessPointSerializer
    queryset = AccessPoint.objects.all()

    def get_queryset(self):
        # super() applies the tenant filter (TenantScopedMixin) — never bypass it
        return (
            super()
            .get_queryset()
            .select_related("tower")
            .annotate(
                client_count=Count(
                    "clients", filter=Q(clients__status__in=Client.ACTIVE_STATUSES)
                )
            )
            .order_by("tower__name", "name")
        )


class ClientViewSet(TenantModelViewSet):
    serializer_class = ClientSerializer
    queryset = Client.objects.select_related("plan", "router").order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        operator = self.get_operator()
        data = serializer.validated_data
        client = create_client(
            operator=operator,
            plan=data.pop("plan"),
            router=data.pop("router"),
            created_by=self.request.user,
            **data,
        )
        serializer.instance = client

    @action(detail=True, methods=["post"])
    def provision(self, request, pk=None):
        client = self.get_object()
        try:
            provision_client(client)
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(ClientSerializer(client).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        client = self.get_object()
        try:
            suspend_client(client, reason="manual")
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": "Suspended", "status": client.status})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        client = self.get_object()
        try:
            restore_client(client)
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": "Restored", "status": client.status})

    @action(detail=True, methods=["get"])
    def live_status(self, request, pk=None):
        """Is this client currently connected? (from /ppp/active)"""
        client = self.get_object()
        try:
            active = {s.username for s in get_adapter(client.router).get_active_pppoe()}
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"online": client.pppoe_username in active})


class InvoiceViewSet(TenantReadOnlyViewSet):
    serializer_class = InvoiceSerializer
    queryset = Invoice.objects.select_related("client").order_by("-issued_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


@extend_schema(responses=OBJECT_RESPONSE, summary="Public: how a suspended subscriber pays")
class SuspendedNoticeView(PublicAPIView):
    """PUBLIC page a suspended PPPoE client is redirected to. Returns the ISP's
    pay instructions, and (if the client's account is known) their balance/status.

    Tenant context: ?router=<id> (the router that redirected them) or the
    subdomain. The client's account may be supplied as ?account=<no> OR resolved
    from their source IP via the router's live PPPoE sessions.

    Anonymous by design — a cut-off subscriber is never a logged-in staff user."""

    def get(self, request):
        from apps.provisioning.models import Router

        # Resolve the ISP
        operator = getattr(request, "tenant", None)
        router = None
        router_id = request.query_params.get("router", "")
        if router_id.isdigit():
            router = Router.objects.filter(pk=int(router_id), is_active=True).first()
            if router and operator is None:
                operator = router.operator
        if operator is None:
            return Response(
                {"detail": "Unknown provider."}, status=status.HTTP_404_NOT_FOUND
            )

        client = None
        account = (request.query_params.get("account") or "").strip().upper()
        if account:
            client = Client.objects.filter(operator=operator, account_number=account).first()
        # Fall back: identify by the client's current PPPoE IP on the router
        if client is None and router is not None:
            src_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            src_ip = src_ip or request.META.get("REMOTE_ADDR", "")
            if src_ip:
                try:
                    active = get_adapter(router).get_active_pppoe()
                    username = next((a.username for a in active if a.ip_address == src_ip), None)
                    if username:
                        client = Client.objects.filter(
                            operator=operator, pppoe_username=username
                        ).first()
                except ProvisioningError:
                    pass

        body = {
            "provider": operator.name,
            "paybill": operator.mpesa_shortcode or None,
            "how_to_pay": (
                "Go to M-Pesa → Lipa na M-Pesa → Pay Bill. Enter the paybill "
                "number, then your account number, then your monthly amount."
            ),
        }
        if client:
            body["client"] = {
                "account_number": client.account_number,
                "full_name": client.full_name,
                "plan": client.plan.name,
                "monthly": str(client.plan.price),
                "balance": str(client.balance),
                "status": client.status,
                "suspended": client.status == Client.Status.SUSPENDED,
            }
        return Response(body)


@extend_schema(responses=OBJECT_RESPONSE, summary="Public: look up a subscriber account")
@api_view(["GET"])
@authentication_classes([])  # anonymous: a suspended subscriber, never staff
@permission_classes([AllowAny])
def account_lookup(request):
    """Public: a suspended client types their account number to see their balance
    and pay instructions. Scoped by ?router= or subdomain tenant."""
    from apps.provisioning.models import Router

    operator = getattr(request, "tenant", None)
    router_id = request.query_params.get("router", "")
    if operator is None and router_id.isdigit():
        router = Router.objects.filter(pk=int(router_id), is_active=True).first()
        operator = router.operator if router else None
    account = (request.query_params.get("account") or "").strip().upper()
    client = (
        Client.objects.filter(operator=operator, account_number=account).first()
        if operator and account
        else None
    )
    if client is None:
        return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(
        {
            "account_number": client.account_number,
            "full_name": client.full_name,
            "plan": client.plan.name,
            "monthly": str(client.plan.price),
            "balance": str(client.balance),
            "status": client.status,
        }
    )
