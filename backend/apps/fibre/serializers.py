from rest_framework import serializers

from apps.core.serializer_fields import TenantPrimaryKeyRelatedField

from .models import FibrePoint, FibreSpan


class FibrePointSerializer(serializers.ModelSerializer):
    # Capacity is never typed: `used` is counted live (customer drops on an ODP; downstream cables
    # on a splitter/cabinet), so it can't drift from reality. `free` = capacity − used, or null
    # where capacity doesn't apply (a pole/closure/handhole).
    used = serializers.SerializerMethodField()
    free = serializers.SerializerMethodField()
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = FibrePoint
        fields = [
            "id", "type", "type_display", "label", "gps_lat", "gps_lng", "status",
            "port_capacity", "splitter_ratio", "notes", "is_active",
            "used", "free", "created_at",
        ]
        read_only_fields = ["is_active", "created_at"]

    def _used(self, obj) -> int:
        if obj.type == FibrePoint.Type.ODP:
            cc = getattr(obj, "anno_clients", None)
            return cc if cc is not None else obj.fibre_clients.count()
        if obj.type in (FibrePoint.Type.SPLITTER, FibrePoint.Type.CABINET):
            dc = getattr(obj, "anno_downstream", None)
            return dc if dc is not None else obj.spans_out.filter(is_active=True).count()
        return 0

    def get_used(self, obj) -> int:
        return self._used(obj)

    def get_free(self, obj) -> int | None:
        if obj.port_capacity <= 0:
            return None
        return max(obj.port_capacity - self._used(obj), 0)


class FibreSpanSerializer(serializers.ModelSerializer):
    # Same-tenant enforced: you can only wire together points this ISP owns.
    from_point = TenantPrimaryKeyRelatedField(queryset=FibrePoint.objects.all())
    to_point = TenantPrimaryKeyRelatedField(queryset=FibrePoint.objects.all())
    from_label = serializers.CharField(source="from_point.label", read_only=True)
    to_label = serializers.CharField(source="to_point.label", read_only=True)

    class Meta:
        model = FibreSpan
        fields = [
            "id", "from_point", "to_point", "from_label", "to_label",
            "cable_type", "fibre_count", "length_m", "status", "notes",
            "is_active", "created_at",
        ]
        read_only_fields = ["is_active", "created_at"]

    def validate(self, attrs):
        # Friendly mirror of the DB CheckConstraint — a cable can't run from a point to itself.
        frm = attrs.get("from_point") or getattr(self.instance, "from_point", None)
        to = attrs.get("to_point") or getattr(self.instance, "to_point", None)
        if frm is not None and to is not None and frm.pk == to.pk:
            raise serializers.ValidationError("A span must connect two different points.")
        return attrs


class AffectedClientSerializer(serializers.Serializer):
    """The compact customer row the blast-radius panel renders."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    account_number = serializers.CharField()
    phone = serializers.CharField()
    status = serializers.CharField()
    plan = serializers.CharField(source="plan.name", default="")
