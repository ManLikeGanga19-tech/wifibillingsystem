from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.public import PublicAPIView
from apps.core.viewsets import TenantReadOnlyViewSet
from apps.plans.models import Plan
from apps.provisioning.models import Router

from .models import Voucher
from .serializers import GenerateBatchSerializer, RedeemSerializer, VoucherSerializer
from .services import VoucherError, generate_batch, redeem


class VoucherViewSet(TenantReadOnlyViewSet):
    serializer_class = VoucherSerializer
    queryset = Voucher.objects.select_related("plan").order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=False, methods=["post"])
    def generate(self, request):
        serializer = GenerateBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        operator = self.get_operator()
        if operator is None:
            return Response({"detail": "No tenant context"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            plan = Plan.objects.get(
                pk=serializer.validated_data["plan_id"], is_active=True, operator=operator
            )
        except Plan.DoesNotExist:
            return Response(
                {"plan_id": "Unknown or inactive plan"}, status=status.HTTP_400_BAD_REQUEST
            )
        created = generate_batch(
            operator=operator,
            plan=plan,
            count=serializer.validated_data["count"],
            prefix=serializer.validated_data["prefix"],
            created_by=request.user,
        )
        return Response(
            VoucherSerializer(created, many=True).data, status=status.HTTP_201_CREATED
        )


class RedeemVoucherView(PublicAPIView):
    """Portal: redeem a printed voucher code. Tenant safety comes from the voucher
    itself — the session lands on the voucher's operator. Anonymous by design."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voucher-redeem"

    def post(self, request):
        serializer = RedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        router = (
            Router.objects.filter(pk=data["router_id"], is_active=True).first()
            if data.get("router_id")
            else None
        )
        try:
            session = redeem(code=data["code"], mac=data["mac"], router=router)
        except VoucherError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "detail": "Voucher accepted",
                "hotspot_username": session.hotspot_username,
                "hotspot_password": session.hotspot_password,
                "expires_at": session.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )
