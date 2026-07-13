import json

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import Operator, OperatorOwnedModel

from .catalog import MANAGED_SMS


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


class MessagingSettings(models.Model):
    """Which gateway each of an ISP's channels leaves through.

    SMS and WhatsApp name an ACTIVE PROVIDER from the catalog (see catalog.py) — one at a
    time. The credentials for each provider live in ProviderCredential, so an ISP can keep
    several configured and switch between them without re-typing keys.

    SMS defaults to the managed WIFI.OS gateway: it works on day one with nothing to set
    up, and is paid for in credits. WhatsApp defaults to nothing at all, because we hold
    no Meta business identity on an ISP's behalf and a channel that silently never sends
    is worse than one that is honestly off.

    Email keeps a simpler shape (our mailer, or the ISP's own SMTP) because there is no
    market of email gateways to choose between — just a server.
    """

    Mode = GatewayMode

    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="messaging"
    )

    # --- SMS: the active provider from catalog.SMS_PROVIDERS --------------------------
    sms_provider = models.CharField(max_length=20, default=MANAGED_SMS)

    # --- WhatsApp: the active provider, or blank for OFF ------------------------------
    whatsapp_provider = models.CharField(max_length=20, blank=True, default="")

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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Messaging for {self.operator.slug}"

    def active_provider(self, channel: str) -> str:
        if channel == Channel.SMS:
            return self.sms_provider or MANAGED_SMS
        if channel == Channel.WHATSAPP:
            return self.whatsapp_provider
        return ""

    def uses_own(self, channel: str) -> bool:
        """True when this channel leaves on the ISP's OWN account rather than ours."""
        if channel == Channel.EMAIL:
            return self.email_mode == self.Mode.OWN and bool(self.smtp_host)
        if channel == Channel.SMS:
            return self.sms_provider not in ("", MANAGED_SMS)
        if channel == Channel.WHATSAPP:
            return bool(self.whatsapp_provider)
        return False


class ProviderCredential(models.Model):
    """One ISP's credentials for ONE gateway.

    Kept out of MessagingSettings so switching providers does not destroy the keys for the
    one you switched away from — an ISP trialling MobileSasa against Africa's Talking
    should not have to re-paste a key to switch back.

    The whole credential set is a single encrypted JSON blob rather than a column per
    field: providers disagree about what a credential even IS (username+key, sid+token,
    id+key+secret), and a schema migration per provider added would be a tax on the one
    thing this design exists to make cheap.
    """

    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="provider_credentials"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    provider = models.CharField(max_length=20)
    #: JSON: {"api_key": "...", "sender_id": "..."} — Fernet-encrypted at rest, and never
    #: returned by the API (reads report which keys are SET, not their values).
    secrets = EncryptedTextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "channel", "provider"], name="one_credential_per_provider"
            )
        ]

    def __str__(self):
        return f"{self.operator.slug} {self.channel}/{self.provider}"

    @property
    def values(self) -> dict:
        if not self.secrets:
            return {}
        try:
            return json.loads(self.secrets)
        except ValueError:
            return {}

    @values.setter
    def values(self, data: dict):
        self.secrets = json.dumps(data)


class SmsCreditEntry(OperatorOwnedModel):
    """SMS credits, as a signed ledger — never a stored balance.

    Same discipline as the wallet (billing.LedgerEntry): the balance is the SUM of what
    happened, so it cannot drift away from its own history. A stored counter that got
    decremented twice on a retry would silently rob an ISP of SMS they paid for, and
    nobody would ever be able to prove it.
    """

    class Reason(models.TextChoices):
        PURCHASE = "purchase", "Credits bought"
        SEND = "send", "Message sent"
        REFUND = "refund", "Refund"
        GRANT = "grant", "Granted by the platform"

    #: Signed: bought is positive, sent is negative.
    credits = models.IntegerField()
    reason = models.CharField(max_length=10, choices=Reason.choices, db_index=True)
    #: The KES this cost, for a purchase. Zero for a send.
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    message = models.ForeignKey(
        "notifications.Message", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credit_entries",
    )
    memo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operator", "created_at"])]
        constraints = [
            # A send debits exactly once per message, however many times the task retries.
            models.UniqueConstraint(
                fields=["message"],
                condition=models.Q(message__isnull=False),
                name="one_credit_debit_per_message",
            )
        ]

    def __str__(self):
        return f"{self.operator.slug} {self.reason} {self.credits:+d}"


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
