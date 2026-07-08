from django.db.models import Count, Max, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from apps.provisioning.models import Session

from .models import User
from .serializers import SubscriberSerializer


class SubscriberViewSet(viewsets.ReadOnlyModelViewSet):
    """Hotspot customers (non-staff users) with session summary for the admin UI."""

    serializer_class = SubscriberSerializer
    permission_classes = [IsAdminUser]
    search_fields = ["phone", "name"]

    def get_queryset(self):
        return (
            User.objects.filter(is_staff=False)
            .annotate(
                last_session_expires=Max("sessions__expires_at"),
                active_sessions=Count(
                    "sessions", filter=Q(sessions__status=Session.Status.ACTIVE)
                ),
            )
            .order_by("-date_joined")
        )
