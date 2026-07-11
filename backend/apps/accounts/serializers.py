from rest_framework import serializers

from .models import Subscriber


class SubscriberSerializer(serializers.ModelSerializer):
    last_session_expires = serializers.DateTimeField(read_only=True)
    active_sessions = serializers.IntegerField(read_only=True)
    date_joined = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Subscriber
        fields = [
            "id",
            "phone",
            "name",
            "email",
            "is_blocked",
            "date_joined",
            "last_session_expires",
            "active_sessions",
        ]
