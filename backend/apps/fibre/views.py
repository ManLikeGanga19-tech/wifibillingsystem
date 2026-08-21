"""Fibre plant API — points, spans, and a point's blast radius. Gated on fibre.write (bundled
with radio plant by default; an Owner can split it on Access Control). Deletes are soft."""

from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import FIBRE_WRITE, MAP_VIEW
from apps.core.permissions import (
    RequireCapability,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantModelViewSet

from .models import FibrePoint, FibreSpan
from .serializers import AffectedClientSerializer, FibrePointSerializer, FibreSpanSerializer
from .services import affected_clients, nearest_point, shortest_path


class _PlantViewSet(TenantModelViewSet):
    """Shared plumbing for points and spans: fibre.write gate, active-by-default listing, and
    soft-delete + restore instead of destroy."""

    read_capability = FIBRE_WRITE
    write_capability = FIBRE_WRITE
    audit_noun = "fibre"

    def _wants_inactive(self) -> bool:
        return str(self.request.query_params.get("include_inactive", "")).lower() in (
            "1", "true", "yes",
        )

    def get_queryset(self):
        qs = super().get_queryset()
        # Active-only unless explicitly asked, or when resolving a row to restore.
        if self.action != "restore" and not self._wants_inactive():
            qs = qs.filter(is_active=True)
        return qs

    def perform_destroy(self, instance):
        # SOFT delete: plant that took a crew a day to record is never one click from gone.
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        audit(f"{self.audit_noun}_deactivated", operator=self.get_operator(),
              actor=self.request.user, target=instance)

    @extend_schema(request=None, responses=OBJECT_RESPONSE)
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        obj = self.get_object()
        obj.is_active = True
        obj.save(update_fields=["is_active"])
        audit(f"{self.audit_noun}_restored", operator=self.get_operator(),
              actor=request.user, target=obj)
        return Response(self.get_serializer(obj).data)


class FibrePointViewSet(_PlantViewSet):
    serializer_class = FibrePointSerializer
    queryset = FibrePoint.objects.all()
    audit_noun = "fibre_point"
    search_fields = ["label", "notes"]
    ordering_fields = ["type", "label", "status"]
    filterset_fields = ["type", "status"]

    def get_queryset(self):
        # Annotate the two "used" counters once, so a list of the whole plant is a single query
        # instead of N. The serializer reads anno_clients / anno_downstream when present.
        return super().get_queryset().annotate(
            anno_clients=Count("fibre_clients", distinct=True),
            anno_downstream=Count("spans_out", filter=Q(spans_out__is_active=True), distinct=True),
        ).order_by("type", "label")

    @extend_schema(responses=OBJECT_RESPONSE,
                   summary="Customers a fault at this point takes offline (blast radius)")
    @action(detail=True, methods=["get"])
    def affected(self, request, pk=None):
        point = self.get_object()
        clients = affected_clients(point)
        return Response({
            "point": {"id": point.id, "label": point.label, "status": point.status},
            "count": clients.count(),
            "clients": AffectedClientSerializer(clients, many=True).data,
        })


class FibreSpanViewSet(_PlantViewSet):
    serializer_class = FibreSpanSerializer
    queryset = FibreSpan.objects.select_related("from_point", "to_point").all()
    audit_noun = "fibre_span"
    search_fields = ["from_point__label", "to_point__label"]
    ordering_fields = ["created_at"]
    filterset_fields = ["cable_type", "status", "from_point", "to_point"]


def _point_json(p: FibrePoint) -> dict:
    return {
        "id": p.id, "label": p.label, "type": p.type,
        "lat": float(p.gps_lat) if p.gps_lat is not None else None,
        "lng": float(p.gps_lng) if p.gps_lng is not None else None,
    }


class FibreRouteView(APIView):
    """Shortest CABLE route through the plant, source → target.

    Gated on map.view (not fibre.write) so a technician standing in the field — any role that can
    see the map — can trace the run to a client or a pole. Source is either a plant point
    (`from_point`) or a raw coordinate (`from_lat`/`from_lng`) that snaps to the nearest point.
    Target is a point (`to_point`) or a customer (`to_client`, routed to their ODP).
    """

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational,
                          RequireCapability(MAP_VIEW)]

    @staticmethod
    def _float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _resolve_source(self, request, op):
        """(point_id, snapped_dict|None) or an error string."""
        raw_point = request.query_params.get("from_point")
        if raw_point:
            p = FibrePoint.objects.filter(operator=op, is_active=True, id=raw_point).first()
            return (p.id, None) if p else "from_point not found."
        lat = self._float(request.query_params.get("from_lat"))
        lng = self._float(request.query_params.get("from_lng"))
        if lat is None or lng is None:
            return "Provide from_point, or from_lat and from_lng."
        snapped, dist = nearest_point(op.id, lat, lng)
        if not snapped:
            return "No placed plant points to route from."
        return (snapped.id, {"point": _point_json(snapped), "distance_m": round(dist, 1)})

    def _resolve_target(self, request, op):
        raw_point = request.query_params.get("to_point")
        if raw_point:
            p = FibrePoint.objects.filter(operator=op, is_active=True, id=raw_point).first()
            return p.id if p else "to_point not found."
        raw_client = request.query_params.get("to_client")
        if raw_client:
            from apps.pppoe.models import Client
            c = (Client.objects.filter(operator=op, id=raw_client)
                 .only("id", "fibre_point_id").first())
            if not c:
                return "to_client not found."
            if not c.fibre_point_id:
                return "That customer isn't attached to a fibre point yet."
            return c.fibre_point_id
        return "Provide to_point or to_client."

    @extend_schema(
        parameters=[
            OpenApiParameter("from_point", int, description="Source plant point id"),
            OpenApiParameter("from_lat", float, description="Source latitude (snaps to nearest)"),
            OpenApiParameter("from_lng", float, description="Source longitude (snaps to nearest)"),
            OpenApiParameter("to_point", int, description="Target plant point id"),
            OpenApiParameter("to_client", int, description="Target customer id (routes to ODP)"),
        ],
        responses=OBJECT_RESPONSE,
        summary="Shortest fibre cable route between two plant points",
    )
    def get(self, request):
        op = acting_tenant(request)
        src = self._resolve_source(request, op)
        if isinstance(src, str):
            return Response({"detail": src}, status=400)
        source_id, snapped = src
        target_id = self._resolve_target(request, op)
        if isinstance(target_id, str):
            return Response({"detail": target_id}, status=400)

        route = shortest_path(op.id, source_id, target_id)
        if route is None:
            return Response(
                {"detail": "No cable path connects those two points."}, status=404)
        return Response({
            "from_snapped": snapped,  # null when source was an explicit point
            "points": [_point_json(p) for p in route["points"]],
            "spans": [
                {"id": s.id, "from_point": s.from_point_id, "to_point": s.to_point_id,
                 "length_m": s.length_m, "cable_type": s.cable_type}
                for s in route["spans"]
            ],
            "total_m": route["total_m"],
            "span_count": route["span_count"],
            "splice_count": route["splice_count"],
        })
