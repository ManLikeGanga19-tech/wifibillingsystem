"""The ISP's settlement account: tell us where to pay you, then prove you own it.

This is the last thing standing between a new ISP and their first shilling, so the
copy matters as much as the code — an ISP who does not understand why their
customers pay US will not complete it.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Operator
from .permissions import CanManageMoney, RequireTenant, TenantIsOperational
from .schema import OBJECT_RESPONSE
from .settlement import (
    MAX_ATTEMPTS,
    SettlementError,
    send_micro_transfer,
    set_settlement_account,
    verify_settlement,
)
from .tenancy import acting_tenant


class SettlementSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Operator.Settlement.choices)
    # paybill
    settlement_paybill = serializers.CharField(max_length=20, required=False, allow_blank=True)
    settlement_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    # bank
    payout_bank_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    payout_bank_account_number = serializers.CharField(
        max_length=40, required=False, allow_blank=True
    )
    payout_bank_account_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )


# NB the name must not collide with any OTHER serializer's component name —
# apps/signup has a VerifySerializer too, and spectacular would silently emit a
# broken schema. See docs/ENGINEERING_NOTES.md #2.
class SettlementVerifySerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=16)


class _Base(APIView):
    # Settlement decides where the ISP's money goes. Only the OWNER may touch it —
    # the same bar as withdrawing, because setting the destination IS withdrawing,
    # one step removed.
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    def handle_exception(self, exc):
        if isinstance(exc, SettlementError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)


def _state(op: Operator) -> dict:
    """Never leaks the reference — the whole proof is that only someone who can see
    the destination account's statement knows it."""
    verifying = bool(op.verification_ref) and not op.settlement_verified_at
    return {
        "method": op.settlement_method or None,
        "destination": op.settlement_destination or None,
        "has_account": op.has_settlement_account,
        "verified": op.settlement_verified_at is not None,
        "verified_at": op.settlement_verified_at,
        "can_transact": op.can_transact,
        "verification": {
            "in_progress": verifying,
            "sent_at": op.verification_sent_at if verifying else None,
            # The AMOUNT is safe to show — it helps them find the row on their
            # statement. The REFERENCE is the secret.
            "amount": op.verification_amount if verifying else None,
            "attempts_left": max(0, MAX_ATTEMPTS - op.verification_attempts)
            if verifying
            else None,
        },
        # Said out loud, because every ISP asks.
        "explainer": (
            "Your customers always pay WIFI.OS, never you directly. We hold that "
            "money, attribute every shilling to you in a ledger you can see, absorb "
            "the M-Pesa and bank charges, and settle to this account on request."
        ),
    }


@extend_schema(request=SettlementSerializer, responses=OBJECT_RESPONSE,
               summary="Where should we pay you? (settlement account)")
class SettlementView(_Base):
    def get(self, request):
        return Response(_state(acting_tenant(request)))

    def post(self, request):
        s = SettlementSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        op = acting_tenant(request)
        set_settlement_account(op, **s.validated_data)
        return Response(_state(op), status=status.HTTP_201_CREATED)


@extend_schema(request=None, responses=OBJECT_RESPONSE,
               summary="Send the proof-of-control micro-transfer")
class SendVerificationView(_Base):
    def post(self, request):
        op = acting_tenant(request)
        send_micro_transfer(op)
        return Response(
            {
                **_state(op),
                "detail": (
                    f"We've sent KSh {op.verification_amount} to "
                    f"{op.settlement_destination}. Find it on your statement and type "
                    "back the reference it carries."
                ),
            }
        )


@extend_schema(request=SettlementVerifySerializer, responses=OBJECT_RESPONSE,
               summary="Read the reference back — this is what switches payments on")
class VerifySettlementView(_Base):
    def post(self, request):
        s = SettlementVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        op = acting_tenant(request)

        verify_settlement(op, s.validated_data["reference"], actor=request.user)
        op.refresh_from_db()

        return Response(
            {
                **_state(op),
                "detail": (
                    "Verified — your payments are ON and your free month has started."
                    if op.can_transact
                    else "Verified. A platform review is required before you go live."
                ),
            }
        )
