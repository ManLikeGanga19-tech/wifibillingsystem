from rest_framework import serializers

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.plans.models import Plan
from apps.provisioning.models import Router

from .models import Transaction


class STKPushRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    plan_id = serializers.IntegerField()
    mac = serializers.CharField(max_length=17, required=False, allow_blank=True, default="")
    router_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_phone(self, value):
        try:
            return normalize_msisdn(value)
        except InvalidPhoneError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        try:
            attrs["plan"] = Plan.objects.get(
                pk=attrs["plan_id"], is_active=True, plan_type=Plan.PlanType.HOTSPOT
            )
        except Plan.DoesNotExist as exc:
            raise serializers.ValidationError({"plan_id": "Unknown or inactive plan"}) from exc
        attrs["router"] = None
        if attrs.get("router_id"):
            attrs["router"] = Router.objects.filter(
                pk=attrs["router_id"], is_active=True
            ).first()
        return attrs


class TransactionStatusSerializer(serializers.ModelSerializer):
    session_active = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "public_id",
            "status",
            "amount",
            "mpesa_receipt",
            "result_desc",
            "session_active",
        ]

    def get_session_active(self, obj) -> bool:
        session = getattr(obj, "session", None)
        return bool(session and session.status == session.Status.ACTIVE)


class TransactionAdminSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "public_id",
            "phone",
            "plan_name",
            "amount",
            "status",
            "mpesa_receipt",
            "checkout_request_id",
            "result_code",
            "result_desc",
            "created_at",
            "callback_received_at",
        ]
