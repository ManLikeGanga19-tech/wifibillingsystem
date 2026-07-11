from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

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

    def get_queryset(self):
        return Tower.objects.annotate(access_point_count=Count("access_points")).order_by("name")


class AccessPointViewSet(TenantModelViewSet):
    serializer_class = AccessPointSerializer

    def get_queryset(self):
        return (
            AccessPoint.objects.select_related("tower")
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
