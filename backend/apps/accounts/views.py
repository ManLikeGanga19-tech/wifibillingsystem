from django.db.models import Count, Max, Q
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.schema import OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantReadOnlyViewSet
from apps.provisioning.models import Session

from .models import Subscriber
from .serializers import SubscriberSerializer


@extend_schema(responses=OBJECT_RESPONSE, summary="Who am I, and which ISP am I acting for")
class MeView(APIView):
    """Who am I + my tenant context — routes the UI between platform view,
    ISP console, and the pending-approval gate."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        operator = user.operator
        acting = acting_tenant(request)

        def as_dict(op):
            if op is None:
                return None
            return {
                "id": op.id,
                "name": op.name,
                "slug": op.slug,
                "status": op.status,
                "is_platform_owned": op.is_platform_owned,
                # Read-only showcase tenant: the console shows a banner and softens write
                # affordances; the API refuses writes regardless (see RequireTenant).
                "is_demo": op.is_demo,
                # THE MONEY GATE, surfaced. The console uses this to explain itself:
                # a pending ISP can build everything but cannot take a shilling, and
                # they must be told exactly why and what to do about it — otherwise
                # every blocked action just looks like a broken product.
                "can_transact": op.can_transact,
                "go_live_blockers": _go_live_blockers(op),
                # Past-due state, so the console can show the banner and (at LOCKED) explain
                # why writes are refused. Derived live — see billing.enforcement.
                "billing": _billing_state(op),
            }

        return Response(
            {
                "phone": user.phone,
                "name": user.name,
                "is_staff": user.is_staff,
                "role": user.role,
                "is_platform_staff": user.is_platform_staff,
                "is_read_only": user.is_read_only,
                "can_manage_money": user.can_manage_money,
                # The resolved capability set for this role — the console hides what the API
                # would refuse anyway. Server stays authoritative; this is only for the UI.
                "capabilities": user.capabilities,
                # Home tenant (the ISP this user belongs to, if any)
                "operator": as_dict(operator),
                # Tenant this request is acting for (platform staff can switch)
                "acting_operator": as_dict(acting),
            }
        )


def _billing_state(op) -> dict:
    """The past-due summary the console banner renders from. `level` is current/warned/
    restricted/locked; the amounts let the banner say exactly what to pay."""
    from apps.billing.enforcement import owed_summary

    return owed_summary(op)


def _go_live_blockers(op) -> list[dict]:
    """What is still standing between this ISP and taking their first payment.

    An empty list means they are live. This is the honest answer to "why can't I
    collect money?", and it is the difference between a product that feels
    deliberate and one that feels broken.
    """
    if op.can_transact:
        return []
    if op.status == op.Status.SUSPENDED:
        return [
            {
                "key": "suspended",
                "label": "Account suspended",
                # Tell them WHY when we know — a suspended-for-non-payment ISP should be
                # told to settle, not left to guess at "contact support".
                "detail": op.suspension_reason or "Contact the platform administrator.",
                "done": False,
                "actionable": False,
            }
        ]
    # PENDING. One thing stands between them and trading: somewhere to be paid.
    # That is the whole bar — because holding a paybill or a business bank account
    # means Safaricom/the bank already ran KYC on them, and we inherit it for free.
    return [
        {
            "key": "settlement_account",
            "label": "Tell us where to pay you",
            "detail": (
                "Add the M-Pesa paybill or bank account we should settle YOUR money "
                "into. Payments switch on the moment you do — no waiting, no "
                "documents. Your customers always pay WIFI.OS; we hold that money, "
                "attribute every shilling to you, absorb the M-Pesa charges, and pay "
                "it out to this account on request."
            ),
            "done": False,
            "actionable": True,
        },
    ]


class SubscriberViewSet(TenantReadOnlyViewSet):
    """ISP customers, always scoped to exactly one tenant.

    Scoping comes from TenantReadOnlyViewSet, NOT from a hand-written filter here. Both
    produce the same rows today, but the mixin also raises if the tenant is somehow
    unresolved, and — more to the point — the one bug this system has shipped twice is a
    queryset that forgot to filter. Every list inheriting the same base is the control.
    """

    read_capability = "clients.view"     # customers are visible to the whole console
    serializer_class = SubscriberSerializer
    queryset = Subscriber.objects.all()

    def get_queryset(self):
        # super() applies the tenant filter (TenantScopedMixin) — never bypass it
        return super().get_queryset().annotate(
            last_session_expires=Max("sessions__expires_at"),
            active_sessions=Count(
                "sessions", filter=Q(sessions__status=Session.Status.ACTIVE)
            ),
        ).order_by("-created_at")
