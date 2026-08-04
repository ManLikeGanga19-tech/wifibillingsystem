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
    # The transfer cost the ISP bore, and what actually reached them (amount minus cost).
    transfer_cost = serializers.DecimalField(
        source="platform_cost", max_digits=12, decimal_places=2, read_only=True
    )
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "operator_name",
            "operator_slug",
            "amount",
            "transfer_cost",
            "net_amount",
            "method",
            "phone",
            "paybill",
            "paybill_account",
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
    """A withdrawal is only an AMOUNT. The destination is the verified settlement
    account — never submitted here, so it can't be redirected without the change-code."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    #: The 6-digit code from the ISP owner's authenticator app — or one of their
    #: recovery codes. Required: this is money leaving our custody.
    mfa_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
