"""Fleet API — a technician reports their own position; a dispatcher sees the live fleet.

Privacy is structural: the ping endpoint writes for request.user ALONE (the technician is never a
request field), and the fleet is gated to dispatchers (fleet.view) with everything tenant-scoped.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.rbac import FLEET_SHARE, FLEET_VIEW
from apps.core.permissions import (
    RequireCapability,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant

from .models import TechLocationPing
from .serializers import FleetMemberSerializer, PingSerializer
from .services import nearest_technicians


class FleetPingView(APIView):
    """A technician's device reports its current position. Writes for the caller only."""

    permission_classes = [IsAuthenticated, RequireTenant, TenantIsOperational,
                          RequireCapability(FLEET_SHARE)]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "fleet-ping"

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Report my current location (technician)")
    def post(self, request):
        s = PingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        TechLocationPing.objects.create(
            operator=acting_tenant(request),
            technician=request.user,   # NEVER from the payload — you can only report yourself
            **s.validated_data,
        )
        return Response({"detail": "Location recorded."}, status=201)


class FleetView(APIView):
    """The live fleet: the latest position per technician, for dispatch. Dispatchers only."""

    permission_classes = [IsAuthenticated, RequireTenant, TenantIsOperational,
                          RequireCapability(FLEET_VIEW)]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Live technician fleet (latest per tech)")
    def get(self, request):
        op = acting_tenant(request)
        cutoff = timezone.now() - timedelta(minutes=settings.FLEET_LIVE_MINUTES)
        # Latest ping per technician (Postgres DISTINCT ON). Order by tech then newest-first so
        # DISTINCT keeps the newest row for each.
        latest = (
            TechLocationPing.objects.filter(operator=op)
            .order_by("technician_id", "-recorded_at")
            .distinct("technician_id")
            .select_related("technician")
        )
        data = FleetMemberSerializer(latest, many=True, context={"live_cutoff": cutoff}).data
        return Response({
            "live_window_minutes": settings.FLEET_LIVE_MINUTES,
            "members": data,
        })


def _parse_coord(request):
    """(lat, lng) from the query, or None — validated to real coordinates."""
    try:
        lat, lng = float(request.query_params["lat"]), float(request.query_params["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


class FleetNearestView(APIView):
    """Live technicians ranked by distance to a coordinate — the primitive behind "dispatch
    nearest". Dispatchers only."""

    permission_classes = [IsAuthenticated, RequireTenant, TenantIsOperational,
                          RequireCapability(FLEET_VIEW)]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Live technicians nearest to lat,lng")
    def get(self, request):
        coord = _parse_coord(request)
        if coord is None:
            return Response({"detail": "Provide a valid lat and lng."}, status=400)
        ranked = nearest_technicians(acting_tenant(request), *coord, live_only=True)
        return Response({
            "target": {"lat": coord[0], "lng": coord[1]},
            "count": len(ranked),
            "technicians": [
                {
                    "technician_id": ping.technician_id,
                    "name": ping.technician.name,
                    "phone": ping.technician.phone,
                    "lat": str(ping.lat), "lng": str(ping.lng),
                    "recorded_at": ping.recorded_at,
                    "distance_km": round(dist, 2),
                }
                for ping, dist in ranked
            ],
        })
