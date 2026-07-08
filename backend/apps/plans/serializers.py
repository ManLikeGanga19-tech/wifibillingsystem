from rest_framework import serializers

from apps.core.services import get_default_operator

from .models import Plan


class PlanSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            "id",
            "name",
            "plan_type",
            "price",
            "duration",
            "duration_seconds",
            "data_cap_mb",
            "download_kbps",
            "upload_kbps",
            "shared_users",
            "mikrotik_profile",
            "description",
            "is_active",
            "sort_order",
        ]

    def create(self, validated_data):
        validated_data.setdefault("operator", get_default_operator())
        return super().create(validated_data)
