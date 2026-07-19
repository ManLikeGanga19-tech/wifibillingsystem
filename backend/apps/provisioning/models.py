import secrets

from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


def _enrollment_token() -> str:
    return secrets.token_urlsafe(32)


def _device_token() -> str:
    """The bearer secret the PAYING device holds to manage the session's other devices.
    Unguessable, so nobody else on an open hotspot can add devices to a session they did
    not pay for."""
    return secrets.token_urlsafe(24)


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

    # Which captive-portal address this router is actually sending customers to, and when
    # we last confirmed it. After a subdomain change these say, per router, whether the
    # new address really landed — an offline router keeps redirecting to the old one, and
    # the ISP deserves to SEE that rather than assume it worked.
    portal_url = models.CharField(max_length=200, blank=True, default="")
    portal_synced_at = models.DateTimeField(null=True, blank=True)
    portal_sync_error = models.CharField(max_length=255, blank=True, default="")

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


class RouterOutage(models.Model):
    """One continuous stretch of a router being unreachable — opened when health monitoring
    first sees it down, closed when it comes back.

    It exists so outage compensation (Settings > Operator alerts) can credit each affected
    PPPoE subscriber the downtime EXACTLY ONCE per outage, and so the ISP has a record of
    when their sites were down. The open row (ended_at IS NULL) is the "currently down" flag;
    there is at most one open outage per router.
    """

    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name="outages")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    #: Set when recovery credited affected subscribers, so a re-run never double-credits.
    compensated_at = models.DateTimeField(null=True, blank=True)
    #: How many PPPoE clients had their expiry extended, and by how long (audit trail).
    compensated_clients = models.PositiveIntegerField(default=0)
    credited_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # At most one OPEN outage per router — the "is it down right now" invariant.
            models.UniqueConstraint(
                fields=["router"], condition=models.Q(ended_at__isnull=True),
                name="one_open_outage_per_router",
            )
        ]

    def __str__(self):
        state = "ongoing" if self.ended_at is None else f"ended {self.ended_at}"
        return f"{self.router.name} outage from {self.started_at} ({state})"

    @property
    def duration_seconds(self) -> int:
        end = self.ended_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds()))


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
    # The subscription clock. TRUE (the default) means the window in expires_at is live.
    # FALSE means the ISP set timer_start_mode="on_login": the session is provisioned but
    # its clock is HELD until the subscriber first connects — the usage sync starts it then,
    # and the expiry sweep ignores held sessions. Existing sessions default TRUE, so nothing
    # about today's on-purchase behaviour changes.
    clock_started = models.BooleanField(default=True)
    # The secret the paying device uses to manage this session's other devices (tap-to-approve).
    device_token = models.CharField(max_length=64, default=_device_token, db_index=True)
    # When we sent the "expiring soon" SMS, so the beat task warns each session exactly
    # once instead of every time it runs.
    expiry_warned_at = models.DateTimeField(null=True, blank=True)
    # Same, for the "you're nearly out of data" SMS on a capped plan.
    data_warned_at = models.DateTimeField(null=True, blank=True)

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

    # -- Multi-device allowance -------------------------------------------
    # The plan sets how many devices may share this one paid session: shared_users general
    # slots (phones/laptops) plus tv_slots dedicated to a television. The tap-to-approve
    # flow enforces each category separately, so adding a TV never costs a phone its slot.
    @property
    def general_slots(self) -> int:
        return self.plan.shared_users

    @property
    def tv_slots(self) -> int:
        return self.plan.tv_slots

    def general_devices_used(self) -> int:
        return self.devices.exclude(kind=SessionDevice.Kind.TV).count()

    def tv_devices_used(self) -> int:
        return self.devices.filter(kind=SessionDevice.Kind.TV).count()


class SessionDevice(OperatorOwnedModel):
    """A device the customer has put on ONE paid session — their paying phone, plus the
    laptops/TV they add via tap-to-approve. Each logs into the hotspot as the session's
    single account, so they share its one time+data budget; this row is our record of who
    is on, and the cap we enforce against the plan's allowance."""

    class Kind(models.TextChoices):
        PHONE = "phone", "Phone"
        LAPTOP = "laptop", "Laptop / computer"
        TV = "tv", "TV"
        OTHER = "other", "Other device"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="devices")
    mac_address = models.CharField(max_length=17)
    hostname = models.CharField(max_length=80, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OTHER)
    #: The device that paid — added automatically, cannot be removed, holds a general slot.
    is_paying_device = models.BooleanField(default=False)
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "mac_address"], name="one_device_row_per_session_mac"
            )
        ]
        indexes = [models.Index(fields=["session", "kind"])]

    def __str__(self):
        return f"{self.mac_address} ({self.kind}) on session #{self.session_id}"
