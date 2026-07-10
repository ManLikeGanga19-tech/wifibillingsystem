from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsPlatformAdmin, TenantIsOperational
from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.tenancy import request_operator
from apps.core.viewsets import TenantReadOnlyViewSet

from .models import LedgerEntry, Payout
from .serializers import LedgerEntrySerializer, PayoutSerializer, WithdrawSerializer
from .services import (
    MINIMUM_PAYOUT,
    WalletError,
    mark_payout_paid,
    reject_payout,
    request_payout,
    wallet_balance,
)


class WalletSummaryView(APIView):
    """ISP wallet: balance + this month's earnings picture."""

    permission_classes = [IsAdminUser, TenantIsOperational]

    def get(self, request):
        operator = request_operator(request)
        if operator is None:
            return Response({"detail": "No tenant context."}, status=status.HTTP_404_NOT_FOUND)
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month = LedgerEntry.objects.filter(operator=operator, created_at__gte=month_start)

        def total(entry_type):
            return month.filter(entry_type=entry_type).aggregate(v=Sum("amount"))["v"] or 0

        return Response(
            {
                "balance": wallet_balance(operator),
                "minimum_payout": MINIMUM_PAYOUT,
                "month_gross": total(LedgerEntry.Type.SALE),
                "month_commission": total(LedgerEntry.Type.COMMISSION),
                "month_fees": total(LedgerEntry.Type.BASE_FEE) + total(LedgerEntry.Type.PPPOE_FEE),
                "month_withdrawn": total(LedgerEntry.Type.PAYOUT),
                "pending_payouts": Payout.objects.filter(
                    operator=operator, status=Payout.Status.REQUESTED
                ).aggregate(v=Sum("amount"))["v"]
                or 0,
                "commission_rate": operator.hotspot_commission_pct,
            }
        )


class LedgerViewSet(TenantReadOnlyViewSet):
    serializer_class = LedgerEntrySerializer
    queryset = LedgerEntry.objects.order_by("-created_at")


class MyPayoutsViewSet(TenantReadOnlyViewSet):
    serializer_class = PayoutSerializer
    queryset = Payout.objects.order_by("-created_at")

    @action(detail=False, methods=["post"])
    def withdraw(self, request):
        operator = self.get_operator()
        if operator is None:
            return Response({"detail": "No tenant context."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            phone = normalize_msisdn(serializer.validated_data["phone"])
        except InvalidPhoneError as exc:
            return Response({"phone": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payout = request_payout(
                operator=operator,
                amount=serializer.validated_data["amount"],
                phone=phone,
                user=request.user,
            )
        except WalletError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


class PlatformPayoutViewSet(viewsets.ReadOnlyModelViewSet):
    """Daniel's payout queue: pay via M-Pesa manually, then record it here."""

    permission_classes = [IsPlatformAdmin]
    serializer_class = PayoutSerializer

    def get_queryset(self):
        qs = Payout.objects.select_related("operator").order_by("-created_at")
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        ref = str(request.data.get("mpesa_reference", "")).strip()
        if not ref:
            return Response(
                {"mpesa_reference": "The M-Pesa transaction code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payout = mark_payout_paid(self.get_object(), by=request.user, mpesa_reference=ref)
        except WalletError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(PayoutSerializer(payout).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        note = str(request.data.get("note", "")).strip() or "Rejected by platform"
        try:
            payout = reject_payout(self.get_object(), by=request.user, note=note)
        except WalletError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(PayoutSerializer(payout).data)
