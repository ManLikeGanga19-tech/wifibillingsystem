from rest_framework import serializers

from .models import LedgerEntry, Payout


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "entry_type", "amount", "memo", "period", "created_at"]


class PayoutSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    operator_slug = serializers.CharField(source="operator.slug", read_only=True)
    destination = serializers.CharField(read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "operator_name",
            "operator_slug",
            "amount",
            "method",
            "phone",
            "bank_name",
            "bank_account_number",
            "bank_account_name",
            "destination",
            "status",
            "mpesa_reference",
            "note",
            "created_at",
            "processed_at",
        ]


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    method = serializers.ChoiceField(choices=["mpesa", "bank"], default="mpesa")
    # M-Pesa
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    # Bank
    bank_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    bank_account_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    bank_account_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
