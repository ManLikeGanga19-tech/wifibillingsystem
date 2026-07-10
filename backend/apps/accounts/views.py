from django.db.models import Count, Max, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantIsOperational
from apps.core.tenancy import request_operator
from apps.provisioning.models import Session

from .models import User
from .serializers import SubscriberSerializer


class MeView(APIView):
    """Who am I + my tenant context. The UI uses this to route between the
    platform view, the ISP console, and the pending-approval gate."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        operator = user.operator
        return Response(
            {
                "phone": user.phone,
                "name": user.name,
                "is_staff": user.is_staff,
                "is_platform_admin": user.is_superuser and user.operator_id is None,
                "operator": (
                    {
                        "id": operator.id,
                        "name": operator.name,
                        "slug": operator.slug,
                        "status": operator.status,
                    }
                    if operator
                    else None
                ),
            }
        )


class SubscriberViewSet(viewsets.ReadOnlyModelViewSet):
    """Hotspot customers with session summary, scoped to the tenant. A customer
    belongs to the tenants they have transacted with (phone numbers are global)."""

    serializer_class = SubscriberSerializer
    permission_classes = [IsAdminUser, TenantIsOperational]

    def get_queryset(self):
        operator = request_operator(self.request)
        qs = User.objects.filter(is_staff=False)
        if operator is not None:
            qs = qs.filter(
                Q(operator=operator)
                | Q(transactions__operator=operator)
                | Q(sessions__operator=operator)
            ).distinct()
        session_filter = Q(sessions__status=Session.Status.ACTIVE)
        if operator is not None:
            session_filter &= Q(sessions__operator=operator)
        return qs.annotate(
            last_session_expires=Max("sessions__expires_at"),
            active_sessions=Count("sessions", filter=session_filter),
        ).order_by("-date_joined")
