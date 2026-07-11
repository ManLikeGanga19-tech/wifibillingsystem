import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.public import PublicAPIView, PublicEndpointMixin
from apps.core.viewsets import TenantReadOnlyViewSet

from .daraja import DarajaError
from .models import Transaction
from .serializers import (
    STKPushRequestSerializer,
    TransactionAdminSerializer,
    TransactionStatusSerializer,
)
from .services import initiate_stk_push, process_stk_callback

logger = logging.getLogger(__name__)


class STKPushView(PublicAPIView):
    """Portal: start an M-Pesa payment. Returns a public_id to poll.

    PublicAPIView => no authentication is attempted. A WiFi customer is anonymous;
    if we let a staff cookie authenticate here, DRF enforces CSRF and the customer
    gets "CSRF Failed" instead of an M-Pesa prompt (cookies ignore the port, so the
    console's cookie reaches the portal in dev)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "stk-push"

    def post(self, request):
        serializer = STKPushRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            tx = initiate_stk_push(
                phone=data["phone"], plan=data["plan"], mac=data["mac"], router=data["router"]
            )
        except DarajaError as exc:
            logger.error("STK push failed: %s", exc)
            return Response(
                {"detail": "Could not reach M-Pesa. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {"transaction_id": tx.public_id, "checkout_request_id": tx.checkout_request_id},
            status=status.HTTP_201_CREATED,
        )


class TransactionStatusView(PublicEndpointMixin, RetrieveAPIView):
    """Portal polls this after STK push until status leaves 'pending'."""

    serializer_class = TransactionStatusSerializer
    queryset = Transaction.objects.select_related("plan")
    lookup_field = "public_id"


@method_decorator(csrf_exempt, name="dispatch")
class DarajaCallbackView(View):
    """Safaricom's STK confirmation webhook. Idempotent; always answers 200 so
    Daraja does not retry storms. The URL embeds a secret token."""

    def post(self, request, token):
        if token != settings.DARAJA_CALLBACK_TOKEN:
            raise Http404
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed callback body: %r", request.body[:500])
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
        try:
            process_stk_callback(payload)
        except Exception:
            # Never bubble a 500 to Safaricom; reconciliation will settle it.
            logger.exception("Callback processing crashed; payload stored for reconciliation")
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@method_decorator(csrf_exempt, name="dispatch")
class C2BConfirmationView(View):
    """Safaricom C2B confirmation for broadband (paybill) payments. Idempotent on
    TransID; matches the account number (BillRefNumber) to a client. Always 200."""

    def post(self, request, token):
        if token != settings.DARAJA_CALLBACK_TOKEN:
            raise Http404
        from .c2b import process_c2b_confirmation

        try:
            payload = json.loads(request.body.decode("utf-8"))
            process_c2b_confirmation(payload)
        except Exception:
            logger.exception("C2B confirmation crashed; not blocking Safaricom")
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@method_decorator(csrf_exempt, name="dispatch")
class C2BValidationView(View):
    """Optional C2B validation: accept only known account numbers. Safaricom
    calls this before confirmation when validation is enabled on the shortcode."""

    def post(self, request, token):
        if token != settings.DARAJA_CALLBACK_TOKEN:
            raise Http404
        from .c2b import find_client

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"ResultCode": "C2B00016", "ResultDesc": "Rejected"})
        if find_client(payload.get("BillRefNumber", "")):
            return JsonResponse({"ResultCode": "0", "ResultDesc": "Accepted"})
        # C2B00012 = invalid account number
        return JsonResponse({"ResultCode": "C2B00012", "ResultDesc": "Invalid account number"})


class TransactionViewSet(TenantReadOnlyViewSet):
    """Admin UI: live transaction feed (tenant-scoped)."""

    serializer_class = TransactionAdminSerializer
    queryset = Transaction.objects.select_related("plan").order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs
