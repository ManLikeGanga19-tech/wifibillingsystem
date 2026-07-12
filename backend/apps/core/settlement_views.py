"""The ISP's settlement account: tell us where to pay you (instant), then confirm
the first payout actually landed there.

The copy matters as much as the code — an ISP who does not understand why their
customers pay US will not finish this, and an ISP who is not told why we want the
code will think it is bureaucracy.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.mfa import MfaError, MfaRequired

from .models import Operator
from .permissions import CanManageMoney, RequireTenant, TenantIsOperational
from .schema import OBJECT_RESPONSE
from .settlement import (
    MAX_ATTEMPTS,
    ChangeCodeRequired,
    SettlementError,
    confirm_payout,
    payout_awaiting_confirmation,
    set_settlement_account,
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
    #: Required only when CHANGING an existing account — emailed to the owner's login
    #: address, which the console cannot reach. First-time setup needs none.
    code = serializers.CharField(max_length=10, required=False, allow_blank=True)


# NB the name must not collide with any OTHER serializer's component name — signup
# has one too, and spectacular would silently emit a broken schema.
# See docs/ENGINEERING_NOTES.md #2.
class ConfirmPayoutSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16)


class _Base(APIView):
    # Settlement decides where the ISP's money goes. Only the OWNER may touch it —
    # the same bar as withdrawing, because setting the destination IS withdrawing,
    # one step removed.
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    def handle_exception(self, exc):
        if isinstance(exc, MfaRequired):
            # They have an authenticator, so THAT is what we ask for — not an emailed
            # code. Offering both would make the change only as strong as the weaker
            # one, and the strong factor would be decoration.
            return Response(
                {"detail": str(exc), "mfa_required": True, "enrolled": True},
                status=status.HTTP_403_FORBIDDEN,
            )
        if isinstance(exc, MfaError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, ChangeCodeRequired):
            # Not a failure — a step. The code is already on its way to the owner's
            # inbox; the UI flips to asking for it.
            return Response(
                {"detail": str(exc), "code_required": True},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(exc, SettlementError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)


def _state(op: Operator) -> dict:
    pending = payout_awaiting_confirmation(op)
    return {
        "method": op.settlement_method or None,
        "destination": op.settlement_destination or None,
        "has_account": op.has_settlement_account,
        "confirmed": op.settlement_verified_at is not None,
        "confirmed_at": op.settlement_verified_at,
        "can_transact": op.can_transact,
        # Changing an existing account takes a code emailed to the owner. Tell the UI
        # up front, so it can warn them BEFORE they fill the form in.
        "change_requires_code": op.has_settlement_account,
        # While this is set, payouts are BLOCKED until they read the code back.
        "awaiting_confirmation": (
            {
                "payout_id": pending.id,
                "amount": pending.amount,
                "sent_at": pending.processed_at,
                "destination": pending.destination,
                "attempts_left": max(0, MAX_ATTEMPTS - op.verification_attempts),
            }
            if pending
            else None
        ),
        # Said out loud, because every ISP asks.
        "explainer": (
            "Your customers always pay WIFI.OS, never you directly. We hold that "
            "money, attribute every shilling to you in a ledger you can see, absorb "
            "the M-Pesa and bank charges, and settle it to this account on request."
        ),
    }


@extend_schema(request=SettlementSerializer, responses=OBJECT_RESPONSE,
               summary="Where should we pay you? (instant — this switches payments on)")
class SettlementView(_Base):
    def get(self, request):
        return Response(_state(acting_tenant(request)))

    def post(self, request):
        s = SettlementSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        op = acting_tenant(request)
        set_settlement_account(op, actor=request.user, **s.validated_data)
        op.refresh_from_db()
        return Response(
            {
                **_state(op),
                "detail": (
                    "Saved — your payments are ON and your free month has started. "
                    "Your first withdrawal will carry a short code; read it back to "
                    "unlock payouts permanently."
                ),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(request=ConfirmPayoutSerializer, responses=OBJECT_RESPONSE,
               summary="Confirm the code that arrived with your first payout")
class ConfirmPayoutView(_Base):
    """Proves the money actually landed where they said it should — and unlocks every
    payout after this one."""

    def post(self, request):
        s = ConfirmPayoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        op = acting_tenant(request)

        confirm_payout(op, s.validated_data["code"], actor=request.user)
        op.refresh_from_db()

        return Response(
            {
                **_state(op),
                "detail": "Confirmed. Your payout account is locked in — withdraw freely.",
            }
        )
