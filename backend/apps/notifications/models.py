from django.conf import settings
from django.db import models

from apps.core.models import OperatorOwnedModel


class Channel(models.TextChoices):
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"


class Campaign(OperatorOwnedModel):
    """A bulk send: one message body fanned out to an audience of clients."""

    class Audience(models.TextChoices):
        ALL = "all", "All clients"
        ACTIVE = "active", "Clients with an active session"
        EXPIRED = "expired", "Clients whose sessions have expired"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        DONE = "done", "Done"

    name = models.CharField(max_length=120)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    audience = models.CharField(max_length=10, choices=Audience.choices, default=Audience.ALL)
    body = models.TextField(max_length=480)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    total_recipients = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.channel} -> {self.audience})"


class Message(OperatorOwnedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.CASCADE, related_name="messages"
    )
    to_phone = models.CharField(max_length=12, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    body = models.TextField(max_length=480)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    provider_ref = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.to_phone} [{self.status}]"
