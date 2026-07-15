from rest_framework import serializers

from apps.core.serializer_fields import TenantPrimaryKeyRelatedField
from apps.ops.models import Equipment
from apps.provisioning.models import Router

from .models import AccessPoint, Client, Invoice, ServicePlan, Tower


class ServicePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePlan
        fields = [
            "id", "name", "price", "download_kbps", "upload_kbps",
            "burst_download_kbps", "burst_upload_kbps", "burst_threshold_download_kbps",
            "burst_threshold_upload_kbps", "burst_time_seconds",
            "data_cap_gb", "mikrotik_profile", "is_active", "sort_order",
        ]


class TowerSerializer(serializers.ModelSerializer):
    access_point_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Tower
        fields = ["id", "name", "gps_lat", "gps_lng", "notes", "is_active", "access_point_count"]


class AccessPointSerializer(serializers.ModelSerializer):
    tower = TenantPrimaryKeyRelatedField(queryset=Tower.objects.all())
    tower_name = serializers.CharField(source="tower.name", read_only=True)
    router = TenantPrimaryKeyRelatedField(
        queryset=Router.objects.all(), required=False, allow_null=True
    )
    equipment = TenantPrimaryKeyRelatedField(
        queryset=Equipment.objects.all(), required=False, allow_null=True
    )
    client_count = serializers.IntegerField(read_only=True)
    utilization = serializers.SerializerMethodField()

    class Meta:
        model = AccessPoint
        fields = [
            "id", "tower", "tower_name", "name", "mode", "band", "frequency",
            "azimuth", "capacity", "router", "equipment", "ssid", "is_active",
            "client_count", "utilization",
        ]

    def get_utilization(self, obj) -> int | None:
        count = getattr(obj, "client_count", None)
        if not obj.capacity or count is None:
            return None
        return round(100 * count / obj.capacity)


class ClientSerializer(serializers.ModelSerializer):
    plan = TenantPrimaryKeyRelatedField(queryset=ServicePlan.objects.all())
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    router = TenantPrimaryKeyRelatedField(queryset=Router.objects.all())
    access_point = TenantPrimaryKeyRelatedField(
        queryset=AccessPoint.objects.all(), required=False, allow_null=True
    )
    cpe_equipment = TenantPrimaryKeyRelatedField(
        queryset=Equipment.objects.all(), required=False, allow_null=True
    )
    # Live metering (pppoe.metering), read-only. `usage` is this cycle's consumption.
    data_cap_gb = serializers.IntegerField(source="plan.data_cap_gb", read_only=True)
    usage = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "account_number", "full_name", "phone", "email", "physical_address",
            "gps_lat", "gps_lng", "plan", "plan_name", "router",
            "pppoe_username", "pppoe_password", "static_ip",
            "delivery_method", "access_point", "cpe_equipment",
            "status", "billing_day", "balance", "next_due_date", "installed_at", "notes",
            "created_at",
            # Live status + usage
            "is_online", "last_online_at", "wan_ip", "session_uptime", "usage_synced_at",
            "data_cap_gb", "usage",
        ]
        read_only_fields = [
            "account_number", "status", "balance", "next_due_date", "created_at",
            "pppoe_username", "pppoe_password",
            "is_online", "last_online_at", "wan_ip", "session_uptime", "usage_synced_at",
        ]

    def get_usage(self, obj) -> dict:
        """This billing cycle's data usage. Cheap: one indexed row per client per period."""
        from .metering import current_period_start
        from .models import ClientUsage

        period = current_period_start(obj)
        row = ClientUsage.objects.filter(client=obj, period_start=period).first()
        down = row.bytes_in if row else 0
        up = row.bytes_out if row else 0
        total = down + up
        cap = obj.plan.data_cap_gb
        pct = round(100 * total / (cap * 1024**3), 1) if cap else None
        return {
            "period_start": period,
            "bytes_down": down,
            "bytes_up": up,
            "bytes_total": total,
            "gb_total": round(total / 1024**3, 2),
            "cap_gb": cap,
            "percent_used": pct,
        }


class InvoiceSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(source="client.account_number", read_only=True)
    client_name = serializers.CharField(source="client.full_name", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "number", "account_number", "client_name", "period_start", "period_end",
            "amount", "due_date", "status", "issued_at", "paid_at",
        ]
