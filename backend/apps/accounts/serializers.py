from rest_framework import serializers

from .models import User


class SubscriberSerializer(serializers.ModelSerializer):
    last_session_expires = serializers.DateTimeField(read_only=True)
    active_sessions = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "name",
            "email",
            "date_joined",
            "last_session_expires",
            "active_sessions",
        ]
