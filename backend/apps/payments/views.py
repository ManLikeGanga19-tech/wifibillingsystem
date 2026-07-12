import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.public import PublicAPIView, PublicEndpointMixin
from apps.core.schema import OBJECT_RESPONSE
from apps.core.viewsets import TenantReadOnlyViewSet
from apps.provisioning.models import Session
from apps.provisioning.services import ReprovisionError, reprovision_transaction

from .daraja import DarajaError
from .models import Transaction
from .serializers import (
    STKPushRequestSerializer,
    TransactionAdminSerializer,
    TransactionStatusSerializer,
)
from .services import ProvisioningUnavailable, initiate_stk_push, process_stk_callback

logger = logging.getLogger(__name__)


@extend_schema(request=STKPushRequestSerializer, responses=OBJECT_RESPONSE,
               summary="Portal: start an M-Pesa STK push")
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
        except ProvisioningUnavailable as exc:
            # No money was taken — we refused before the push. 409, not 502: nothing
            # is broken on M-Pesa's side; this hotspot simply cannot serve yet.
            return Response(
                {"detail": str(exc), "reason": "no_router"},
                status=status.HTTP_409_CONFLICT,
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


@extend_schema(request=None, responses=OBJECT_RESPONSE,
               summary="Re-attempt the connection for a paid transaction")
class RetryProvisionView(PublicAPIView):
    """The customer paid, provisioning failed, and they tapped "retry".

    Anonymous on purpose (a hotspot customer has no login) and safe to be so: it is
    keyed by the transaction's unguessable public_id, it only ever RE-ATTEMPTS a
    connection the customer already paid for, and it moves no money. The worst an
    abuser can do is enqueue a provisioning attempt for a transaction they already
    know the id of — which does nothing but reconnect its rightful owner.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "stk-push"

    def post(self, request, public_id):
        tx = Transaction.objects.select_related("session").filter(public_id=public_id).first()
        if tx is None:
            return Response({"detail": "Unknown payment."}, status=status.HTTP_404_NOT_FOUND)
        if tx.status not in Transaction.SUCCESS_STATUSES:
            return Response(
                {"detail": "That payment hasn't completed yet."},
                status=status.HTTP_409_CONFLICT,
            )

        from apps.provisioning.tasks import provision_transaction

        # Clear the recorded transaction-level failure so the portal flips back to
        # "connecting" immediately rather than showing stale "failed" until the task
        # runs. The session (if any) is re-driven by the task itself.
        if tx.provision_error:
            tx.provision_error = ""
            tx.save(update_fields=["provision_error", "updated_at"])
        provision_transaction.delay(tx.id)
        return Response({"detail": "Reconnecting you now.", "provisioning": "connecting"})


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

        client = find_client(payload.get("BillRefNumber", ""))
        # Reject BEFORE the money leaves the customer. If we accept here we are
        # obliged to hold funds for an ISP we have not verified; refusing means the
        # payer keeps their money and simply tries again once the ISP is live.
        if client and not client.operator.can_transact:
            return JsonResponse(
                {"ResultCode": "C2B00012", "ResultDesc": "This account is not active yet"}
            )
        if client:
            return JsonResponse({"ResultCode": "0", "ResultDesc": "Accepted"})
        # C2B00012 = invalid account number
        return JsonResponse({"ResultCode": "C2B00012", "ResultDesc": "Invalid account number"})


class TransactionViewSet(TenantReadOnlyViewSet):
    """Admin UI: live transaction feed (tenant-scoped)."""

    serializer_class = TransactionAdminSerializer
    queryset = Transaction.objects.select_related("plan", "session").order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        # "Paid but never connected" — the queue the ISP works from. A paid transaction
        # (incl. reconciled) whose session is not ACTIVE, or that has no session at all.
        if self.request.query_params.get("unconnected"):
            qs = qs.filter(status__in=Transaction.SUCCESS_STATUSES).exclude(
                session__status=Session.Status.ACTIVE
            )
        return qs

    @extend_schema(request=None, responses=OBJECT_RESPONSE,
                   summary="Reconnect a paid customer who never got online (fresh window)")
    @action(detail=True, methods=["post"])
    def reconnect(self, request, pk=None):
        """The ISP reconnecting a paid customer manually — the far-away-customer case.

        NOT gated by the money-impersonation block: reconnecting delivers a service the
        customer already paid for, it moves no money, and it is exactly what platform
        support should be able to do while helping. Read-only support still can't (they
        can't write anything), which is correct."""
        tx = self.get_object()  # tenant-scoped by TenantScopedMixin
        try:
            session = reprovision_transaction(tx, actor=request.user, compensate=True)
        except ReprovisionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        tx.refresh_from_db()
        return Response(
            {
                **TransactionAdminSerializer(tx).data,
                "detail": (
                    "Reconnecting them now with a fresh "
                    f"{tx.plan.name} — their time starts over."
                ),
                "new_expiry": session.expires_at.isoformat(),
            }
        )
