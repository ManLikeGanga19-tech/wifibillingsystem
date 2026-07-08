from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


class Router(OperatorOwnedModel):
    class Backend(models.TextChoices):
        MIKROTIK_REST = "mikrotik_rest", "MikroTik RouterOS v7 REST"
        DUMMY = "dummy", "Dummy (dev/testing)"

    class Status(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"
        UNKNOWN = "unknown", "Unknown"

    name = models.CharField(max_length=80, help_text="Site name, e.g. 'Kibera Site A'")
    management_host = models.CharField(
        max_length=100, help_text="WireGuard IP or public IP the server reaches the router on"
    )
    api_port = models.PositiveIntegerField(default=443)
    username = models.CharField(max_length=60, default="admin")
    password = EncryptedTextField(blank=True)
    use_tls = models.BooleanField(default=True)
    verify_tls = models.BooleanField(
        default=False, help_text="Off by default: routers use self-signed certs"
    )
    provisioning_backend = models.CharField(
        max_length=20, choices=Backend.choices, default=Backend.MIKROTIK_REST
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNKNOWN)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.management_host})"

    @property
    def rest_base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.management_host}:{self.api_port}/rest"


class Session(OperatorOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending provision"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        SUSPENDED = "suspended", "Suspended"
        FAILED = "failed", "Provisioning failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="sessions")
    router = models.ForeignKey(Router, on_delete=models.PROTECT, related_name="sessions")
    transaction = models.OneToOneField(
        "payments.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="session",
    )
    voucher = models.OneToOneField(
        "vouchers.Voucher",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="session",
    )
    hotspot_username = models.CharField(max_length=60)
    hotspot_password = models.CharField(max_length=60, blank=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    mac_address = models.CharField(max_length=17, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    data_used_mb = models.PositiveIntegerField(default=0)
    provision_error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(transaction__isnull=False) | models.Q(voucher__isnull=False),
                name="session_has_payment_source",
            )
        ]

    def __str__(self):
        return f"{self.hotspot_username} on {self.router.name} [{self.status}]"
