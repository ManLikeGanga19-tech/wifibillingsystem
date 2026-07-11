from django.db.models import Count, Max, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.tenancy import acting_tenant
from apps.provisioning.models import Session

from .models import Subscriber
from .serializers import SubscriberSerializer


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
