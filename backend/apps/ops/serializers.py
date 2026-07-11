from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import Subscriber, User
from apps.core.serializer_fields import TenantPrimaryKeyRelatedField
from apps.provisioning.models import Router

from .models import Equipment, Expense, Lead, Ticket


class TicketSerializer(serializers.ModelSerializer):
    subscriber_phone = serializers.CharField(source="subscriber.phone", read_only=True, default="")
    # Tenant-scoped: cannot attach another ISP's customer or assign to their staff
    subscriber = TenantPrimaryKeyRelatedField(
        queryset=Subscriber.objects.all(), required=False, allow_null=True
    )
    assigned_to = TenantPrimaryKeyRelatedField(
        queryset=User.objects.filter(is_staff=True), required=False, allow_null=True
    )

    class Meta:
        model = Ticket
        fields = [
            "id",
            "subject",
            "description",
            "subscriber",
            "subscriber_phone",
            "status",
            "priority",
            "assigned_to",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = ["resolved_at"]

    def update(self, instance, validated_data):
        new_status = validated_data.get("status", instance.status)
        is_closing = new_status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)
        if is_closing and not instance.resolved_at:
            instance.resolved_at = timezone.now()
        elif new_status in Ticket.OPEN_STATUSES:
            instance.resolved_at = None
        return super().update(instance, validated_data)


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = ["id", "name", "phone", "location", "source", "status", "notes", "created_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    router_name = serializers.CharField(source="router.name", read_only=True, default="")
    router = TenantPrimaryKeyRelatedField(
        queryset=Router.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Expense
        fields = [
            "id",
            "date",
            "category",
            "description",
            "amount",
            "router",
            "router_name",
            "created_at",
        ]


class EquipmentSerializer(serializers.ModelSerializer):
    router_name = serializers.CharField(source="router.name", read_only=True, default="")
    router = TenantPrimaryKeyRelatedField(
        queryset=Router.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Equipment
        fields = [
            "id",
            "name",
            "equipment_type",
            "serial_number",
            "status",
            "router",
            "router_name",
            "cost",
            "notes",
            "created_at",
        ]
