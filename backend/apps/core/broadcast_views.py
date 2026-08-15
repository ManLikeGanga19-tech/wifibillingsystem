"""Platform broadcasts — Danamo speaking to every ISP console at once.

Two audiences, two permission levels:
  * Platform (super-admin): the OWNER composes/retires broadcasts; staff may read them.
  * Tenant (ISP console): ANY signed-in user sees the live, undismissed ones and can wave
    a dismissable one away for themselves.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BroadcastDismissal, PlatformBroadcast
from .permissions import IsPlatformOwner, IsPlatformStaff
from .schema import OBJECT_RESPONSE
from .services import audit


class PlatformBroadcastSerializer(serializers.ModelSerializer):
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = PlatformBroadcast
        fields = [
            "id", "title", "body", "level", "dismissable", "is_active",
            "starts_at", "ends_at", "created_at", "is_live",
        ]
        read_only_fields = ["created_at"]

    def get_is_live(self, obj) -> bool:
        return obj.is_live()


class PlatformBroadcastViewSet(viewsets.ModelViewSet):
    """Compose + manage the messages shown across every ISP console. Reading is open to
    platform staff; creating/editing/retiring one is the owner's call (it speaks in Danamo's
    name to every tenant) and is audited."""

    serializer_class = PlatformBroadcastSerializer
    queryset = PlatformBroadcast.objects.all()

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsPlatformStaff()]
        return [IsPlatformOwner()]

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        audit("broadcast_created", actor=self.request.user, target=obj,
              level=obj.level, title=obj.title)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit("broadcast_updated", actor=self.request.user, target=obj, is_active=obj.is_active)

    def perform_destroy(self, instance):
        audit("broadcast_deleted", actor=self.request.user, target=instance, title=instance.title)
        instance.delete()


class TenantBroadcastSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformBroadcast
        fields = ["id", "title", "body", "level", "dismissable", "starts_at"]


@extend_schema(responses=TenantBroadcastSerializer(many=True),
               summary="Live broadcasts for the signed-in user")
class ActiveBroadcastsView(APIView):
    """What THIS user should see right now: live broadcasts they haven't dismissed. Any
    signed-in console user (ISP or platform) — audience is every tenant."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        dismissed = BroadcastDismissal.objects.filter(
            user=request.user
        ).values_list("broadcast_id", flat=True)
        live = (
            PlatformBroadcast.objects.filter(is_active=True, starts_at__lte=now)
            .exclude(ends_at__lte=now)
            .exclude(id__in=dismissed)
        )
        return Response(TenantBroadcastSerializer(live, many=True).data)


@extend_schema(request=None, responses=OBJECT_RESPONSE, summary="Dismiss a broadcast for me")
class DismissBroadcastView(APIView):
    """Wave a broadcast away for yourself. A pinned (non-dismissable) one refuses."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            b = PlatformBroadcast.objects.get(pk=pk)
        except PlatformBroadcast.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not b.dismissable:
            return Response({"detail": "This notice can't be dismissed."},
                            status=status.HTTP_400_BAD_REQUEST)
        BroadcastDismissal.objects.get_or_create(broadcast=b, user=request.user)
        return Response({"detail": "Dismissed."})
