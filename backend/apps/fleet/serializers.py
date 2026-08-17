from rest_framework import serializers

from .models import TechLocationPing


class PingSerializer(serializers.Serializer):
    """What a technician's device POSTs. Deliberately minimal — a fix, nothing identifying: the
    technician is always request.user (never a field), so no one can report for someone else."""

    lat = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    accuracy = serializers.IntegerField(required=False, min_value=0, allow_null=True)
    heading = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
        min_value=0, max_value=360,
    )


class FleetMemberSerializer(serializers.ModelSerializer):
    """A technician's latest known position for the dispatch map."""

    technician_id = serializers.IntegerField(source="technician.id")
    name = serializers.CharField(source="technician.name")
    phone = serializers.CharField(source="technician.phone")
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = TechLocationPing
        fields = ["technician_id", "name", "phone", "lat", "lng", "accuracy", "heading",
                  "recorded_at", "is_live"]

    def get_is_live(self, obj) -> bool:
        # The view passes the cutoff so every row is judged against one clock.
        cutoff = self.context.get("live_cutoff")
        return bool(cutoff and obj.recorded_at >= cutoff)
