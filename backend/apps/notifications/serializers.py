from rest_framework import serializers

from .models import Campaign, Message


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "channel",
            "audience",
            "subject",
            "body",
            "status",
            "total_recipients",
            "sent_count",
            "failed_count",
            "created_at",
        ]
        read_only_fields = ["status", "total_recipients", "sent_count", "failed_count"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "campaign",
            "to_phone",
            "to_email",
            "channel",
            "subject",
            "body",
            "status",
            "provider_ref",
            "error",
            "sent_at",
            "created_at",
        ]
