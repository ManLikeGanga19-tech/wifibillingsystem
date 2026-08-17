"""The Map page's data: every geolocated thing an ISP owns, on one Kenya canvas.

Read-only and strictly tenant-scoped — a map of customers' home coordinates is sensitive PII,
so it never leaves the operator that owns it and is never public. Phase 1 layers: network
towers, PPPoE clients, and MikroTik routers (the three that carry gps_lat/gps_lng). Each layer
returns MINIMAL points ({id, lat, lng, status, label}) so a tenant with thousands of clients
stays cheap; the frontend clusters. Records without coordinates are counted (`unplaced`) rather
than dropped, so nothing is silently invisible — the console can prompt to place them.
"""

from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import BUSINESS_LOCATION_WRITE, MAP_VIEW
from apps.core.permissions import (
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireCapability,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant


def _has_coords(qs):
    return qs.exclude(gps_lat__isnull=True).exclude(gps_lng__isnull=True)


class MapDataView(APIView):
    """All of this ISP's map points in one call, grouped by layer, plus how many of each still
    need a pin, plus a sensible centre for the initial viewport."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational,
                          RequireCapability(MAP_VIEW)]

    @extend_schema(responses=OBJECT_RESPONSE,
                   summary="Tenant map points (towers, clients, routers, leads)")
    def get(self, request):
        from apps.ops.models import Lead
        from apps.pppoe.models import Client, Tower
        from apps.provisioning.models import Router

        op = acting_tenant(request)

        towers_qs = Tower.objects.filter(operator=op)
        clients_qs = Client.objects.filter(operator=op)
        routers_qs = Router.objects.filter(operator=op, is_active=True)
        # Leads that aren't dead — an open pipeline of demand. Lost/converted leads aren't
        # "where to expand", so they're excluded from the map (converted ones are clients now).
        leads_qs = Lead.objects.filter(
            operator=op, status__in=[Lead.Status.NEW, Lead.Status.CONTACTED]
        )

        towers = [
            {"id": t.id, "lat": float(t.gps_lat), "lng": float(t.gps_lng),
             "label": t.name, "status": "up"}
            for t in _has_coords(towers_qs).only("id", "gps_lat", "gps_lng", "name")
        ]
        # A client is plotted where they LIVE; colour carries their billing status so a whole
        # red patch (suspended) or grey (churned) reads at a glance.
        clients = [
            {"id": c.id, "lat": float(c.gps_lat), "lng": float(c.gps_lng),
             "label": c.full_name, "status": c.status, "account": c.account_number,
             "connection": c.connection_type, "phone": c.phone,
             "plan": c.plan.name if c.plan_id else ""}
            for c in _has_coords(clients_qs).select_related("plan").only(
                "id", "gps_lat", "gps_lng", "full_name", "status",
                "account_number", "connection_type", "phone", "plan__name",
            )
        ]
        routers = [
            {"id": r.id, "lat": float(r.gps_lat), "lng": float(r.gps_lng),
             "label": r.name, "status": r.status}
            for r in _has_coords(routers_qs).only("id", "gps_lat", "gps_lng", "name", "status")
        ]
        leads = [
            {"id": ld.id, "lat": float(ld.gps_lat), "lng": float(ld.gps_lng),
             "label": ld.name, "status": ld.status, "phone": ld.phone, "source": ld.source}
            for ld in _has_coords(leads_qs).only(
                "id", "gps_lat", "gps_lng", "name", "status", "phone", "source")
        ]

        # The map opens on: the ISP's business location if they've set it, else the centroid of
        # their placed assets, else nothing (the client falls back to the device location).
        business = (
            {"lat": float(op.gps_lat), "lng": float(op.gps_lng)}
            if op.gps_lat is not None and op.gps_lng is not None else None
        )
        pts = towers + clients + routers + leads
        centroid = (
            {"lat": sum(p["lat"] for p in pts) / len(pts),
             "lng": sum(p["lng"] for p in pts) / len(pts)}
            if pts else None
        )

        return Response({
            "business_location": business,
            "layers": {"towers": towers, "clients": clients, "routers": routers, "leads": leads},
            "counts": {"towers": len(towers), "clients": len(clients),
                       "routers": len(routers), "leads": len(leads)},
            # placed vs total, so the UI can say "12 of 40 routers need a pin"
            "unplaced": {
                "towers": towers_qs.count() - len(towers),
                "clients": clients_qs.count() - len(clients),
                "routers": routers_qs.count() - len(routers),
                "leads": leads_qs.count() - len(leads),
            },
            # `center` = the best default viewport: business location wins, else the asset
            # centroid. None means "use the device's current location" on the client.
            "center": business or centroid,
        })


class BusinessLocationView(APIView):
    """Where the ISP's business physically sits — the Map's home. Owner/admin sets it (usually
    from the 'set your business location' prompt on the Map, pre-filled with their device's
    current position). Tenant-scoped; support is read-only."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAdminUser(), RequireTenant(), TenantIsOperational(),
                    RequireCapability(MAP_VIEW)]
        # Setting the base of operations is an Owner/Admin decision, not the front desk or field.
        return [IsAdminUser(), RequireTenant(), TenantIsOperational(),
                ReadOnlyForSupport(), NotBillingLocked(),
                RequireCapability(BUSINESS_LOCATION_WRITE)]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's business location")
    def get(self, request):
        op = acting_tenant(request)
        placed = op.gps_lat is not None and op.gps_lng is not None
        return Response({
            "gps_lat": float(op.gps_lat) if placed else None,
            "gps_lng": float(op.gps_lng) if placed else None,
        })

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Set this ISP's business location")
    def post(self, request):
        op = acting_tenant(request)
        lat, lng = request.data.get("gps_lat"), request.data.get("gps_lng")
        if lat in (None, "") and lng in (None, ""):
            op.gps_lat = op.gps_lng = None  # clearing it is allowed
        else:
            try:
                op.gps_lat, op.gps_lng = Decimal(str(lat)), Decimal(str(lng))
            except (TypeError, ValueError, InvalidOperation):
                return Response({"detail": "Enter a valid latitude and longitude."}, status=400)
            if not (-90 <= op.gps_lat <= 90 and -180 <= op.gps_lng <= 180):
                return Response({"detail": "Those coordinates are out of range."}, status=400)
        op.save(update_fields=["gps_lat", "gps_lng", "updated_at"])
        audit("business_location_set", operator=op, actor=request.user, target=op,
              gps_lat=str(op.gps_lat), gps_lng=str(op.gps_lng))
        return Response({
            "detail": "Business location saved.",
            "gps_lat": float(op.gps_lat) if op.gps_lat is not None else None,
            "gps_lng": float(op.gps_lng) if op.gps_lng is not None else None,
        })
