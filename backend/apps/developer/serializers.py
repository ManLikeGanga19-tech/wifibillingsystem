from rest_framework import serializers

from .events import EVENT_KEYS
from .models import ApiToken, Webhook


class ApiTokenSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiToken
        fields = ["id", "name", "prefix", "last_used_at", "created_at", "is_active"]
        read_only_fields = ["prefix", "last_used_at", "created_at", "is_active"]


def _secret_preview(secret: str) -> str:
    secret = secret or ""
    if len(secret) < 12:
        return "••••"
    return f"{secret[:9]}…{secret[-4:]}"


class WebhookSerializer(serializers.ModelSerializer):
    # Provided only when creating (optional — blank auto-generates). Never read back in full.
    secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    secret_preview = serializers.SerializerMethodField()

    class Meta:
        model = Webhook
        fields = [
            "id", "label", "url", "events", "is_active", "secret", "secret_preview",
            "last_delivered_at", "last_status", "last_error", "created_at",
        ]
        read_only_fields = ["last_delivered_at", "last_status", "last_error", "created_at"]

    def get_secret_preview(self, obj) -> str:
        return _secret_preview(obj.secret)

    def validate_events(self, value):
        unknown = [e for e in value if e not in EVENT_KEYS]
        if unknown:
            raise serializers.ValidationError(f"Unknown event(s): {', '.join(unknown)}")
        return list(dict.fromkeys(value))  # dedupe, keep order

    def create(self, validated_data):
        # Blank/absent secret -> let the model's generate_secret default mint one.
        if not validated_data.get("secret"):
            validated_data.pop("secret", None)
        return super().create(validated_data)
