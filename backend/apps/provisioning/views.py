import json

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import ROUTER_ACCESS
from apps.core.permissions import IsPlatformOwner, IsPlatformStaff
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
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
    read_capability = ROUTER_ACCESS      # MikroTik access — Owner/Admin/Technician
    search_fields = ["name", "management_host", "serial_number"]
    ordering_fields = ["name", "status", "last_seen_at"]
    filterset_fields = ["status", "is_active", "provisioning_backend"]
    write_capability = ROUTER_ACCESS

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
        """Manual 'reconcile now': live-test the router, update its status, and re-push
        session state. The periodic health check owns passive status; this is the button
        for 'don't wait — recover and sync it right now'."""
        router = self.get_object()
        if not router.is_reachable:
            # A wiped/factory-reset router has no API user to talk to — re-syncing
            # is impossible until the ISP re-runs the setup script.
            return Response(
                {
                    "detail": "This router can't be reached. Re-run its setup script "
                    "to reconnect it, then sessions will re-sync.",
                    "needs_onboarding": True,
                },
                status=status.HTTP_409_CONFLICT,
            )
        # LIVE check, not the cached flag: a just-rebooted router recovers immediately, and
        # if it is still booting we say so instead of queueing a sync that will fail.
        if router.provisioning_backend != router.Backend.DUMMY:
            from .adapters import ProvisioningAuthError
            from .tasks import _apply_reachability

            try:
                ok = get_adapter(router).test_connection()
            except ProvisioningAuthError as exc:
                _apply_reachability(router, ok=False, auth_failed=True)
                return Response(
                    {"detail": str(exc), "needs_onboarding": True},
                    status=status.HTTP_409_CONFLICT,
                )
            except ProvisioningError:
                _apply_reachability(router, ok=False, auth_failed=False)
                return Response(
                    {
                        "detail": "Can't reach the router yet. If you just powered it on, "
                        "give it a minute to reconnect, then try again.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            _apply_reachability(router, ok=ok, auth_failed=False)
        sync_router.delay(router.id)
        return Response(
            {"detail": "Reconnected — re-sync queued."}, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        from .adapters import ProvisioningAuthError
        from .services import refresh_device_identity
        from .tasks import _apply_reachability

        router = self.get_object()
        try:
            ok = get_adapter(router).test_connection()
        except ProvisioningAuthError as exc:
            _apply_reachability(router, ok=False, auth_failed=True)
            return Response(
                {"ok": False, "needs_onboarding": True, "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ProvisioningError as exc:
            return Response({"ok": False, "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        _apply_reachability(router, ok=ok, auth_failed=False)
        if ok:
            refresh_device_identity(router)  # capture version/model/serial while here
        return Response({"ok": ok})

    @action(detail=True, methods=["get"])
    def device_info(self, request, pk=None):
        """Live hardware + health for this router. Also refreshes the stored
        identity fields. Transient metrics (uptime, cpu, memory) are not stored."""
        from .services import refresh_device_identity

        router = self.get_object()
        info = refresh_device_identity(router)
        if info is None:
            return Response(
                {"detail": "Could not reach the router."}, status=status.HTTP_502_BAD_GATEWAY
            )
        return Response(
            {
                "routeros_version": info.routeros_version,
                "board_name": info.board_name,
                "serial_number": info.serial_number,
                "architecture": info.architecture,
                "identity_name": info.identity_name,
                "uptime": info.uptime,
                "cpu_load": info.cpu_load,
                "free_memory": info.free_memory,
                "total_memory": info.total_memory,
                "active_users": info.active_users,
            }
        )

    @action(detail=True, methods=["get"])
    def active_sessions(self, request, pk=None):
        router = self.get_object()
        try:
            sessions = get_adapter(router).get_active_sessions()
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response([vars(s) for s in sessions])

    @extend_schema(responses=OBJECT_RESPONSE, summary="Live slow-speed diagnostics for a router")
    @action(detail=True, methods=["get"])
    def diagnose(self, request, pk=None):
        """Read-only 'why are clients slow?' snapshot: CPU/mem, the MSS clamp, queue count,
        live throughput, plus the oversubscription ratio (sold Mbps vs this site's uplink).
        Touches nothing on the router — safe to run against production at peak."""
        router = self.get_object()
        try:
            diag = get_adapter(router).get_speed_diagnostics()
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        sold_mbps, active_clients = self._sold_download_mbps(router)
        ratio = (sold_mbps / router.uplink_mbps) if router.uplink_mbps else None
        return Response(
            {
                "reachable": diag.reachable,
                "cpu_load": diag.cpu_load,
                "mem_used_pct": diag.mem_used_pct,
                "uptime": diag.uptime,
                "mss_clamp_present": diag.mss_clamp_present,
                "simple_queue_count": diag.simple_queue_count,
                "pppoe_active_count": diag.pppoe_active_count,
                "top_interfaces": [vars(i) for i in diag.top_interfaces],
                "notes": diag.notes,
                "active_clients": active_clients,
                "sold_download_mbps": round(sold_mbps, 1),
                "uplink_mbps": router.uplink_mbps,
                "oversubscription_ratio": round(ratio, 1) if ratio is not None else None,
            }
        )

    @extend_schema(responses=OBJECT_RESPONSE, summary="Recent load trend for a router")
    @action(detail=True, methods=["get"], url_path="health-trend")
    def health_trend(self, request, pk=None):
        """CPU / memory / active-user samples over the retention window, plus the 24h peaks —
        so a nightly saturation spike is visible without having to look at peak in person."""
        from datetime import timedelta

        from django.db.models import Max

        from .models import RouterHealthSample

        router = self.get_object()
        since = timezone.now() - timedelta(days=7)
        samples = list(
            RouterHealthSample.objects.filter(router=router, sampled_at__gte=since)
            .order_by("sampled_at")
            .values("sampled_at", "cpu_load", "mem_used_pct", "active_users")
        )
        day_ago = timezone.now() - timedelta(hours=24)
        peaks = RouterHealthSample.objects.filter(
            router=router, sampled_at__gte=day_ago
        ).aggregate(cpu=Max("cpu_load"), mem=Max("mem_used_pct"), users=Max("active_users"))
        return Response(
            {
                "samples": [
                    {
                        "at": s["sampled_at"].isoformat(),
                        "cpu_load": s["cpu_load"],
                        "mem_used_pct": s["mem_used_pct"],
                        "active_users": s["active_users"],
                    }
                    for s in samples
                ],
                "peak_cpu_24h": peaks["cpu"],
                "peak_mem_24h": peaks["mem"],
                "peak_users_24h": peaks["users"],
            }
        )

    def _sold_download_mbps(self, router) -> tuple[float, int]:
        """Aggregate download Mbps sold to the ACTIVE clients on this router — the numerator of
        the oversubscription ratio."""
        from apps.pppoe.models import Client

        active = Client.objects.filter(
            router=router, status=Client.Status.ACTIVE
        ).select_related("plan")
        total_kbps = sum((c.plan.download_kbps or 0) for c in active)
        return total_kbps / 1000, active.count()


@extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
               summary="Router setup-script phone-home (enrollment token auth)")
@csrf_exempt
@api_view(["POST"])
@authentication_classes([])  # the ROUTER calls this, never a browser/staff user
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

    # Where we reach the router back. With the WireGuard hub live, that's the router's
    # stable overlay /32 — never its public/CGNAT source IP. Before the hub exists we fall
    # back to the IP the platform saw the phone-home come from (the pilot LAN model).
    from .wireguard import hub_configured

    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    source_ip = (xff.split(",")[0].strip() if xff else "") or request.META.get("REMOTE_ADDR", "")

    if hub_configured() and router.overlay_ip:
        router.management_host = router.overlay_ip
        router.wg_enrolled_at = timezone.now()
    else:
        router.management_host = source_ip
    router.api_port = 80  # REST over www; production tightens to 443
    router.use_tls = False
    router.password = payload.get("api_password", "")
    router.routeros_version = str(payload.get("version", ""))[:20]
    router.enrolled_at = timezone.now()
    router.status = Router.Status.ONLINE
    router.last_seen_at = timezone.now()
    router.onboarding_required = False  # fresh script run — creds are good again
    router.save()  # full save — persists all enrollment fields at once
    audit(
        "router_enrolled",
        operator=router.operator,
        target=router,
        source_ip=source_ip,
        version=router.routeros_version,
    )
    # Pull full hardware identity (model, serial, architecture) now that we can reach it
    from .services import refresh_device_identity

    refresh_device_identity(router)
    return Response({"detail": "enrolled", "router": router.name})


class SessionViewSet(TenantReadOnlyViewSet):
    read_capability = ROUTER_ACCESS      # live sessions are a network diagnostic
    serializer_class = SessionSerializer
    queryset = (
        Session.objects.select_related("plan", "router", "subscriber")
        .prefetch_related("devices")  # the per-session device list, without an N+1
        .order_by("-created_at")
    )
    search_fields = ["hotspot_username", "mac_address", "ip_address", "subscriber__phone"]
    ordering_fields = ["starts_at", "expires_at", "status"]
    filterset_fields = ["status", "router", "plan"]

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


@extend_schema(responses=OBJECT_RESPONSE, summary="WireGuard hub config (render only)")
class WireGuardHubConfigView(APIView):
    """The hub's wg-quick config, reconciled from the enrolled-router registry. READ-ONLY: it
    RENDERS text for an operator to review and apply on the hub host — it never connects to a
    router or the hub, so it cannot affect any live customer. Owner-only (the peer set is
    sensitive, and the interface stanza can carry the hub key)."""

    permission_classes = [IsPlatformOwner]

    def get(self, request):
        from .wireguard import hub_configured, render_hub_config

        audit("wireguard_hub_config_rendered", actor=request.user)
        return Response({
            "hub_configured": hub_configured(),
            "config": render_hub_config(),
        })


@extend_schema(responses=OBJECT_RESPONSE, summary="WireGuard per-router tunnel health")
class WireGuardHealthView(APIView):
    """Per-router tunnel liveness (up / stale / down), derived from the last handshake we've
    already observed. A pure read — no network activity, nothing pushed."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        from .wireguard import tunnel_health

        return Response({"routers": tunnel_health()})
