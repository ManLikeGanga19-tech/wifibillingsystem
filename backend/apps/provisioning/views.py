from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .adapters import ProvisioningError, get_adapter
from .models import Router, Session
from .serializers import RouterSerializer, SessionSerializer
from .tasks import suspend_session


class RouterViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
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


class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = SessionSerializer
    queryset = Session.objects.select_related("plan", "router", "user").order_by("-created_at")

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
