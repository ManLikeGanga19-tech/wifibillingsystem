from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.services import get_default_operator
from apps.plans.models import Plan
from apps.provisioning.models import Router

from .models import Voucher
from .serializers import GenerateBatchSerializer, RedeemSerializer, VoucherSerializer
from .services import VoucherError, generate_batch, redeem


class VoucherViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = VoucherSerializer
    queryset = Voucher.objects.select_related("plan").order_by("-created_at")

    @action(detail=False, methods=["post"])
    def generate(self, request):
        serializer = GenerateBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            plan = Plan.objects.get(pk=serializer.validated_data["plan_id"], is_active=True)
        except Plan.DoesNotExist:
            return Response(
                {"plan_id": "Unknown or inactive plan"}, status=status.HTTP_400_BAD_REQUEST
            )
        created = generate_batch(
            operator=get_default_operator(),
            plan=plan,
            count=serializer.validated_data["count"],
            prefix=serializer.validated_data["prefix"],
            created_by=request.user,
        )
        return Response(
            VoucherSerializer(created, many=True).data, status=status.HTTP_201_CREATED
        )


class RedeemVoucherView(APIView):
    """Portal: redeem a printed voucher code."""

    permission_classes = [AllowAny]
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
