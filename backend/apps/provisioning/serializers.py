from rest_framework import serializers

from .models import Router, Session


class RouterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Router
        fields = [
            "id",
            "name",
            "management_host",
            "api_port",
            "username",
            "password",
            "use_tls",
            "verify_tls",
            "provisioning_backend",
            "status",
            "last_seen_at",
            "is_active",
        ]
        read_only_fields = ["status", "last_seen_at"]


class SessionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    router_name = serializers.CharField(source="router.name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True, default="")

    class Meta:
        model = Session
        fields = [
            "id",
            "phone",
            "hotspot_username",
            "plan_name",
            "router_name",
            "status",
            "starts_at",
            "expires_at",
            "mac_address",
            "ip_address",
            "data_used_mb",
            "provision_error",
        ]
