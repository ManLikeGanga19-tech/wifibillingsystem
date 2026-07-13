from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import Operator, OperatorOwnedModel


class Channel(models.TextChoices):
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"


class GatewayMode(models.TextChoices):
    PLATFORM = "platform", "Use the WIFI.OS platform gateway"
    OWN = "own", "Use my own gateway"
    OFF = "off", "Disabled"


#: SMS and email offer the same two modes. Defined ONCE, at module level, so the model
#: field, the serializer and drf-spectacular's ENUM_NAME_OVERRIDES all describe the same
#: choice set — otherwise the schema grows a second name for the same enum.
GATEWAY_MODE_CHOICES = [
    (GatewayMode.PLATFORM.value, GatewayMode.PLATFORM.label),
    (GatewayMode.OWN.value, GatewayMode.OWN.label),
]

#: WhatsApp has no platform account, so its modes are off/own rather than platform/own.
WHATSAPP_MODE_CHOICES = [
    (GatewayMode.OFF.value, GatewayMode.OFF.label),
    (GatewayMode.OWN.value, GatewayMode.OWN.label),
]


class MessagingSettings(models.Model):
    """Which gateway an ISP's messages leave through.

    Hybrid by design. Out of the box an ISP sends on the PLATFORM's accounts and has
    nothing to configure — messaging works on day one, which is the whole point of a
    SaaS. An ISP who outgrows that (wants their own sender ID, their own SMS rate, their
    own From: address) switches a channel to `own` and supplies credentials, and from
    that moment their traffic leaves on their account and is billed to them.

    WhatsApp has no platform default: we hold no Meta business account on an ISP's
    behalf, so the honest default is OFF rather than a channel that silently never sends.

    Every credential here is a secret the ISP trusted us with — all of them are stored
    with EncryptedTextField (Fernet, key from the environment) and NONE of them are ever
    returned by the API. See messaging_views: reads report `*_configured: true`, not the
    value.
    """

    #: Kept as a class attribute so callers can write MessagingSettings.Mode.OWN.
    Mode = GatewayMode

    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="messaging"
    )

    # --- SMS -------------------------------------------------------------------------
    sms_mode = models.CharField(
        max_length=10, choices=GATEWAY_MODE_CHOICES, default=GatewayMode.PLATFORM
    )
    sms_username = models.CharField(max_length=100, blank=True)
    sms_api_key = EncryptedTextField(blank=True, default="")
    # The name a customer sees the SMS come FROM. Africa's Talking requires this to be a
    # sender ID they have approved for the account — an unapproved one silently fails,
    # which is exactly what the test-send button exists to catch.
    sms_sender_id = models.CharField(max_length=11, blank=True)

    # --- Email -----------------------------------------------------------------------
    email_mode = models.CharField(
        max_length=10, choices=GATEWAY_MODE_CHOICES, default=GatewayMode.PLATFORM
    )
    smtp_host = models.CharField(max_length=200, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True)
    smtp_password = EncryptedTextField(blank=True, default="")
    smtp_use_tls = models.BooleanField(default=True)
    from_email = models.EmailField(blank=True)
    from_name = models.CharField(max_length=80, blank=True)

    # --- WhatsApp --------------------------------------------------------------------
    whatsapp_mode = models.CharField(
        max_length=10, choices=WHATSAPP_MODE_CHOICES, default=GatewayMode.OFF
    )
    whatsapp_phone_number_id = models.CharField(max_length=50, blank=True)
    whatsapp_token = EncryptedTextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Messaging for {self.operator.slug}"

    def uses_own(self, channel: str) -> bool:
        """True when this channel should leave on the ISP's OWN credentials.

        Guards on the credentials themselves, not just the mode: an ISP who flips to
        `own` but saves a blank key must not have their messages silently vanish — they
        fall back to the platform, which is the behaviour that keeps customers informed.
        """
        if channel == Channel.SMS:
            return self.sms_mode == self.Mode.OWN and bool(self.sms_api_key)
        if channel == Channel.EMAIL:
            return self.email_mode == self.Mode.OWN and bool(self.smtp_host)
        if channel == Channel.WHATSAPP:
            return self.whatsapp_mode == self.Mode.OWN and bool(self.whatsapp_token)
        return False


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
    subject = models.CharField(max_length=150, blank=True, help_text="Email channel only")
    body = models.TextField(max_length=2000)
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

    class Category(models.TextChoices):
        # What the message IS — so reporting can separate "we sent 4,000 marketing
        # blasts" from "we sent 4,000 payment receipts", and so a per-category opt-out
        # is possible later.
        CAMPAIGN = "campaign", "Marketing campaign"
        PAYMENT = "payment", "Payment confirmation"
        EXPIRY = "expiry", "Expiry warning"
        PPPOE = "pppoe", "PPPoE notice"
        OTHER = "other", "Other"

    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.CASCADE, related_name="messages"
    )
    category = models.CharField(
        max_length=12, choices=Category.choices, default=Category.CAMPAIGN, db_index=True
    )
    to_phone = models.CharField(max_length=12, blank=True, db_index=True)
    to_email = models.EmailField(blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    subject = models.CharField(max_length=150, blank=True)
    body = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    provider_ref = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def recipient(self) -> str:
        return self.to_email if self.channel == Channel.EMAIL else self.to_phone

    def __str__(self):
        return f"{self.channel} to {self.recipient} [{self.status}]"
