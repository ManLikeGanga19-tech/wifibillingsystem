from rest_framework import serializers

from .models import LedgerEntry, Payout


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "entry_type", "amount", "memo", "period", "created_at"]


class PayoutSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    operator_slug = serializers.CharField(source="operator.slug", read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "operator_name",
            "operator_slug",
            "amount",
            "phone",
            "status",
            "mpesa_reference",
            "note",
            "created_at",
            "processed_at",
        ]


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    phone = serializers.CharField(max_length=20)
