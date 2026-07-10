import json

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.services import audit
from apps.core.viewsets import TenantModelViewSet, TenantReadOnlyViewSet

from .adapters import ProvisioningError, get_adapter
from .models import Router, Session
from .onboarding import generate_setup_script
from .serializers import RouterSerializer, SessionSerializer
from .tasks import suspend_session, sync_router


class RouterViewSet(TenantModelViewSet):
    serializer_class = RouterSerializer
    queryset = Router.objects.all()

    @action(detail=True, methods=["get"])
    def setup_script(self, request, pk=None):
        """The one-paste RouterOS script the ISP runs on their MikroTik."""
        router = self.get_object()
        return Response(
            {
                "script": generate_setup_script(router),
                "enrolled": router.is_enrolled,
                "status": router.status,
            }
        )

    @action(detail=True, methods=["post"])
    def resync(self, request, pk=None):
        router = self.get_object()
        if not router.is_enrolled:
            return Response(
                {"detail": "Router has not enrolled yet."}, status=status.HTTP_409_CONFLICT
            )
        sync_router.delay(router.id)
        return Response({"detail": "Re-sync queued."}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        router = self.get_object()
        try:
            ok = get_adapter(router).test_connection()
        except ProvisioningError as exc:
            return Response({"ok": False, "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"ok": ok})

    @action(detail=True, methods=["get"])
    def active_sessions(self, request, pk=None):
        router = self.get_object()
        try:
            sessions = get_adapter(router).get_active_sessions()
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response([vars(s) for s in sessions])


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def router_enroll(request):
    """Phone-home from the setup script. Authenticated by the router's unique
    enrollment token; records the API password and the source IP as the
    management host, then flips the router online."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return Response({"detail": "Bad payload"}, status=status.HTTP_400_BAD_REQUEST)

    token = payload.get("token", "")
    router = Router.objects.filter(enrollment_token=token).first()
    if router is None:
        return Response({"detail": "Unknown enrollment token"}, status=status.HTTP_404_NOT_FOUND)

    # The IP the platform sees is where it must reach the router back
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    source_ip = (xff.split(",")[0].strip() if xff else "") or request.META.get("REMOTE_ADDR", "")

    router.management_host = source_ip
    router.api_port = 80  # REST over www; production tightens to 443
    router.use_tls = False
    router.password = payload.get("api_password", "")
    router.routeros_version = str(payload.get("version", ""))[:20]
    router.enrolled_at = timezone.now()
    router.status = Router.Status.ONLINE
    router.last_seen_at = timezone.now()
    router.save()  # full save — persists all enrollment fields at once
    audit(
        "router_enrolled",
        operator=router.operator,
        target=router,
        source_ip=source_ip,
        version=router.routeros_version,
    )
    return Response({"detail": "enrolled", "router": router.name})


class SessionViewSet(TenantReadOnlyViewSet):
    serializer_class = SessionSerializer
    queryset = Session.objects.select_related("plan", "router", "user").order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        session = self.get_object()
        if session.status != Session.Status.ACTIVE:
            return Response(
                {"detail": f"Session is {session.status}, not active"},
                status=status.HTTP_409_CONFLICT,
            )
        suspend_session.delay(session.pk, Session.Status.SUSPENDED)
        return Response({"detail": "Suspension queued"}, status=status.HTTP_202_ACCEPTED)
