from django.db.models import Count, Max, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantIsOperational
from apps.core.tenancy import request_operator
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
    """ISP customers, scoped to the tenant. Subscribers are per-operator by
    construction, so scoping is a plain operator filter — no cross-tenant joins."""

    serializer_class = SubscriberSerializer
    permission_classes = [IsAdminUser, TenantIsOperational]

    def get_queryset(self):
        operator = request_operator(self.request)
        qs = Subscriber.objects.all()
        if operator is not None:
            qs = qs.filter(operator=operator)
        return qs.annotate(
            last_session_expires=Max("sessions__expires_at"),
            active_sessions=Count(
                "sessions", filter=Q(sessions__status=Session.Status.ACTIVE)
            ),
        ).order_by("-created_at")
