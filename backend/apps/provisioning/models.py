import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


def _enrollment_token() -> str:
    return secrets.token_urlsafe(32)


class Router(OperatorOwnedModel):
    class Backend(models.TextChoices):
        MIKROTIK_REST = "mikrotik_rest", "MikroTik RouterOS v7 REST"
        DUMMY = "dummy", "Dummy (dev/testing)"

    class Status(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"
        PENDING = "pending", "Awaiting first contact"
        UNKNOWN = "unknown", "Unknown"

    name = models.CharField(max_length=80, help_text="Site name, e.g. 'Kibera Site A'")
    management_host = models.CharField(
        max_length=100,
        blank=True,
        help_text="Filled automatically when the router phones home (its WireGuard/LAN IP)",
    )
    api_port = models.PositiveIntegerField(default=443)
    username = models.CharField(max_length=60, default="wifios")
    password = EncryptedTextField(blank=True)
    use_tls = models.BooleanField(default=True)
    verify_tls = models.BooleanField(
        default=False, help_text="Off by default: routers use self-signed certs"
    )
    provisioning_backend = models.CharField(
        max_length=20, choices=Backend.choices, default=Backend.MIKROTIK_REST
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # Self-onboarding
    enrollment_token = models.CharField(
        max_length=64, unique=True, default=_enrollment_token, editable=False
    )
    enrolled_at = models.DateTimeField(null=True, blank=True)
    routeros_version = models.CharField(max_length=20, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.management_host or 'not enrolled'})"

    @property
    def rest_base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.management_host}:{self.api_port}/rest"

    @property
    def is_enrolled(self) -> bool:
        return bool(self.enrolled_at and self.management_host)

    def mark_seen(self, online: bool):
        self.status = self.Status.ONLINE if online else self.Status.OFFLINE
        if online:
            self.last_seen_at = timezone.now()
        self.save(update_fields=["status", "last_seen_at", "updated_at"])


class RouterHealthCheck(models.Model):
    """Append-only health history for uptime reporting."""

    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name="health_checks")
    online = models.BooleanField()
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-checked_at"]

    def __str__(self):
        return f"{self.router.name} {'up' if self.online else 'down'} @ {self.checked_at}"


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
