import secrets

from django.db import models

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
    last_sync_at = models.DateTimeField(null=True, blank=True)

    # Hardware identity — refreshed from the device on every successful connection,
    # so it's populated whether the router self-onboarded or was set up by hand.
    routeros_version = models.CharField(max_length=20, blank=True)
    board_name = models.CharField(max_length=60, blank=True)
    serial_number = models.CharField(max_length=40, blank=True)
    architecture = models.CharField(max_length=30, blank=True)
    identity_updated_at = models.DateTimeField(null=True, blank=True)
    # Set when a connection attempt is rejected for bad credentials (factory reset
    # wiped the API user). Cleared on the next successful connection.
    onboarding_required = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.management_host or 'not enrolled'})"

    @property
    def rest_base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.management_host}:{self.api_port}/rest"

    @property
    def is_enrolled(self) -> bool:
        """Went through the self-onboarding script (phoned home)."""
        return bool(self.enrolled_at and self.management_host)

    @property
    def is_reachable(self) -> bool:
        """We have the credentials to talk to it via the API and they haven't been
        rejected. Gates provisioning and re-sync (not is_enrolled) so a
        hand-configured router works too. DUMMY backend is always reachable."""
        if self.provisioning_backend == self.Backend.DUMMY:
            return True
        return bool(self.management_host and self.password) and not self.onboarding_required

    @property
    def needs_onboarding(self) -> bool:
        """The ISP must (re)run the setup script: either it was never configured,
        or a factory reset wiped its API user (a connection auth-failure). A router
        that is merely powered off is NOT here — its config is intact and it
        re-syncs automatically when it returns."""
        no_credentials = not (self.management_host and self.password)
        return self.provisioning_backend != self.Backend.DUMMY and (
            no_credentials or self.onboarding_required
        )


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

    subscriber = models.ForeignKey(
        "accounts.Subscriber",
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
    # When we sent the "expiring soon" SMS, so the beat task warns each session exactly
    # once instead of every time it runs.
    expiry_warned_at = models.DateTimeField(null=True, blank=True)

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
