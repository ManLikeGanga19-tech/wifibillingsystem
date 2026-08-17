"""Fibre plant API — points, spans, and a point's blast radius. Gated on fibre.write (bundled
with radio plant by default; an Owner can split it on Access Control). Deletes are soft."""

from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.rbac import FIBRE_WRITE
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.viewsets import TenantModelViewSet

from .models import FibrePoint, FibreSpan
from .serializers import AffectedClientSerializer, FibrePointSerializer, FibreSpanSerializer
from .services import affected_clients


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
