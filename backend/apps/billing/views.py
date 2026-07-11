from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import (
    CanManageMoney,
    IsPlatformOwner,
    IsPlatformStaff,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.tenancy import acting_tenant
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
    """ISP wallet: balance + this month's earnings picture. Tenant-only."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    def get(self, request):
        operator = acting_tenant(request)
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
    """Withdrawals are money movement: ISP OWNER only (a manager runs ops but
    cannot move cash out; support is read-only)."""

    serializer_class = PayoutSerializer
    queryset = Payout.objects.order_by("-created_at")
    permission_classes = [
        *TenantReadOnlyViewSet.permission_classes,
        CanManageMoney,
    ]

    @action(detail=False, methods=["post"])
    def withdraw(self, request):
        operator = self.get_operator()
        serializer = WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        method = data["method"]

        destination = {}
        if method == "mpesa":
            try:
                destination["phone"] = normalize_msisdn(data.get("phone", ""))
            except InvalidPhoneError as exc:
                return Response({"phone": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            destination = {
                "bank_name": data.get("bank_name", ""),
                "bank_account_number": data.get("bank_account_number", ""),
                "bank_account_name": data.get("bank_account_name", ""),
            }
        try:
            payout = request_payout(
                operator=operator,
                amount=data["amount"],
                user=request.user,
                method=method,
                destination=destination,
            )
        except WalletError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


class PlatformPayoutViewSet(viewsets.ReadOnlyModelViewSet):
    """The platform payout queue: pay via M-Pesa manually, then record it here.
    Platform staff may view; only the platform owner may pay or reject."""

    serializer_class = PayoutSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsPlatformStaff()]
        return [IsPlatformOwner()]

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
