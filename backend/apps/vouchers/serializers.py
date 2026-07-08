from rest_framework import serializers

from .models import Voucher


class VoucherSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Voucher
        fields = [
            "id",
            "code",
            "plan",
            "plan_name",
            "batch_id",
            "status",
            "redeemed_at",
            "printed",
            "created_at",
        ]


class GenerateBatchSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    count = serializers.IntegerField(min_value=1, max_value=1000)
    prefix = serializers.CharField(max_length=6, required=False, allow_blank=True, default="")


class RedeemSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    mac = serializers.CharField(max_length=17, required=False, allow_blank=True, default="")
    router_id = serializers.IntegerField(required=False, allow_null=True, default=None)
