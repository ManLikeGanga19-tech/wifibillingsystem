"""Top-up endpoints: the ISP paying WIFI.OS.

Note what is deliberately NOT here: a second factor. Every other money endpoint demands a
TOTP because it moves the ISP's money OUT (a payout) or spends what we hold for them. A
top-up moves money IN, to their own account, from their own phone, and Safaricom already
demands their M-Pesa PIN. Asking for an authenticator code on top would be security
theatre that costs them a sale.
"""

import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import CanManageMoney, RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant

from . import platform_account, topup
from .models import TopUp
from .topup import TopUpError

logger = logging.getLogger(__name__)


def _summary(operator) -> dict:
    bal = platform_account.balance(operator)
    settings_row = _alert_settings(operator)
    return {
        "balance": str(bal),
        # In shillings AND in messages, because "KSh 640" means nothing to someone
        # deciding whether they can send tonight's reminders.
        "sms_remaining": max(int(bal / platform_account.SMS_PRICE), 0) if bal > 0 else 0,
        "sms_price": str(platform_account.SMS_PRICE),
        "low": bal <= settings_row.low_balance_threshold,
        "can_send_sms": bal > 0,
        "low_balance_threshold": str(settings_row.low_balance_threshold),
        "alert_phones": settings_row.alert_phones,
        "bundles": [
            {
                "id": b.id,
                "price": str(b.price),
                "credit": str(b.credit),
                "bonus": str(b.bonus),
                "sms": b.sms,
                "per_sms": str(b.per_sms),
            }
            for b in platform_account.BUNDLES
        ],
        "min_topup": str(platform_account.MIN_TOPUP),
    }


def _alert_settings(operator):
    from apps.notifications.models import MessagingSettings

    row, _ = MessagingSettings.objects.get_or_create(operator=operator)
    return row


class PlatformAccountView(APIView):
    """The ISP's balance with us, and what they can buy."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's platform balance")
    def get(self, request):
        return Response(_summary(acting_tenant(request)))


class PlatformInvoicesView(APIView):
    """The ISP's monthly statements from WIFI.OS — an itemised record of every fee."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's monthly platform statements")
    def get(self, request):
        from .models import PlatformInvoice

        operator = acting_tenant(request)
        invoices = PlatformInvoice.objects.filter(operator=operator)[:24]
        return Response(
            {
                "invoices": [
                    {
                        "period": inv.period,
                        "issued_at": inv.issued_at,
                        "status": inv.status,
                        "paid_at": inv.paid_at,
                        "total": str(inv.total),
                        "lines": [
                            {"label": "Monthly subscription", "amount": str(inv.base_fee),
                             "due": True},
                            {"label": "PPPoE per-user fees", "amount": str(inv.pppoe_fee),
                             "due": True},
                            {"label": "One-time setup fee", "amount": str(inv.setup_fee),
                             "due": True},
                            {"label": "Commission on your own-gateway sales",
                             "amount": str(inv.direct_commission), "due": True},
                            {"label": "SMS", "amount": str(inv.sms), "due": True},
                            {"label": "Commission on WIFI.OS-paybill sales (already deducted)",
                             "amount": str(inv.withheld_commission), "due": False},
                        ],
                    }
                    for inv in invoices
                ]
            }
        )


class TopUpSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    bundle = serializers.CharField(max_length=20, required=False, allow_blank=True)
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )

    def validate(self, data):
        if not data.get("bundle") and data.get("amount") is None:
            raise serializers.ValidationError("Choose a bundle or enter an amount.")
        return data


class TopUpView(APIView):
    """Start an STK push so the ISP can pay us."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=TopUpSerializer, responses=OBJECT_RESPONSE, summary="Top up by M-Pesa (STK)"
    )
    def post(self, request):
        s = TopUpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            row = topup.initiate(
                operator=acting_tenant(request),
                phone=s.validated_data["phone"],
                bundle_id=s.validated_data.get("bundle", ""),
                amount=s.validated_data.get("amount"),
                user=request.user,
            )
        except TopUpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": row.id,
                "amount": str(row.amount),
                "credit": str(row.credit),
                "status": row.status,
                "detail": f"Enter your M-Pesa PIN on {row.phone} to pay KSh {row.amount:,.0f}.",
            }
        )


class TopUpStatusView(APIView):
    """Polled while the ISP is entering their PIN."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Is this top-up paid yet?")
    def get(self, request, pk: int):
        operator = acting_tenant(request)
        row = TopUp.objects.filter(pk=pk, operator=operator).first()
        if row is None:
            raise Http404
        return Response(
            {
                "id": row.id,
                "status": row.status,
                "amount": str(row.amount),
                "credit": str(row.credit),
                "mpesa_receipt": row.mpesa_receipt,
                "result_desc": row.result_desc,
                "account": _summary(operator),
            }
        )


class AlertSettingsSerializer(serializers.Serializer):
    low_balance_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False
    )
    alert_phones = serializers.ListField(
        child=serializers.CharField(max_length=20), required=False, max_length=5
    )


class LowBalanceAlertView(APIView):
    """Who we warn, and when, before their SMS stops going out."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=AlertSettingsSerializer,
        responses=OBJECT_RESPONSE,
        summary="Low-balance alert threshold and phone numbers",
    )
    def patch(self, request):
        from apps.core.phone import InvalidPhoneError, normalize_msisdn

        s = AlertSettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        row = _alert_settings(operator)

        if "low_balance_threshold" in s.validated_data:
            row.low_balance_threshold = s.validated_data["low_balance_threshold"]
        if "alert_phones" in s.validated_data:
            cleaned = []
            for raw in s.validated_data["alert_phones"]:
                try:
                    cleaned.append(normalize_msisdn(raw))
                except InvalidPhoneError:
                    return Response(
                        {"detail": f"{raw} is not a valid Kenyan number."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            row.alert_phones = cleaned
        row.save()
        return Response(_summary(operator))


@method_decorator(csrf_exempt, name="dispatch")
class TopUpCallbackView(View):
    """Safaricom's STK confirmation for a TOP-UP.

    Its own URL, separate from the subscriber-payment callback: this money flows the other
    way (the ISP pays US), and landing it in the subscriber handler would credit an ISP for
    a sale no customer made. Always answers 200 — Daraja retries badly on anything else,
    and reconciliation is what actually guarantees the result.
    """

    def post(self, request, token):
        if token != settings.DARAJA_CALLBACK_TOKEN:
            raise Http404
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed top-up callback body: %r", request.body[:500])
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
        try:
            topup.handle_callback(payload)
        except Exception:
            # Never bubble a 500 to Safaricom; the reconciler will settle it.
            logger.exception("Top-up callback crashed; reconciliation will settle it")
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
