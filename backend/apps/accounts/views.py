from django.db.models import Count, Max, Q
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant
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
                # THE MONEY GATE, surfaced. The console uses this to explain itself:
                # a pending ISP can build everything but cannot take a shilling, and
                # they must be told exactly why and what to do about it — otherwise
                # every blocked action just looks like a broken product.
                "can_transact": op.can_transact,
                "go_live_blockers": _go_live_blockers(op),
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
                # Home tenant (the ISP this user belongs to, if any)
                "operator": as_dict(operator),
                # Tenant this request is acting for (platform staff can switch)
                "acting_operator": as_dict(acting),
            }
        )


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
                "detail": "Contact the platform administrator.",
                "actionable": False,
            }
        ]
    # PENDING. Phase B2 adds the settlement-account check here; today the bar is a
    # platform review.
    return [
        {
            "key": "settlement_account",
            "label": "Add your settlement account",
            "detail": (
                "Tell us the M-Pesa paybill or bank account we should pay YOU into. "
                "Your customers always pay WIFI.OS; we hold the money, attribute it "
                "to you, and settle it to this account."
            ),
            "actionable": True,
        },
        {
            "key": "verification",
            "label": "We verify your business",
            "detail": (
                "We check the settlement account really belongs to you. Once it does, "
                "payments switch on and your free month starts."
            ),
            "actionable": False,
        },
    ]


class SubscriberViewSet(viewsets.ReadOnlyModelViewSet):
    """ISP customers, always scoped to exactly one tenant."""

    serializer_class = SubscriberSerializer
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    def get_queryset(self):
        operator = acting_tenant(self.request)
        return Subscriber.objects.filter(operator=operator).annotate(
            last_session_expires=Max("sessions__expires_at"),
            active_sessions=Count(
                "sessions", filter=Q(sessions__status=Session.Status.ACTIVE)
            ),
        ).order_by("-created_at")
