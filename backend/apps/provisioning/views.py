from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.viewsets import TenantModelViewSet, TenantReadOnlyViewSet

from .adapters import ProvisioningError, get_adapter
from .models import Router, Session
from .serializers import RouterSerializer, SessionSerializer
from .tasks import suspend_session


class RouterViewSet(TenantModelViewSet):
    serializer_class = RouterSerializer
    queryset = Router.objects.all()

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
