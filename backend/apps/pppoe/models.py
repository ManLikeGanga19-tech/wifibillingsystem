"""Broadband (PPPoE) domain — isolated from hotspot.

A ServicePlan is the monthly package; a Client is a contracted account an ISP
sets up; Invoice is the monthly bill. Tower/AccessPoint model the wireless
topology (PTP/PTMP) for capacity tracking. Provisioning uses /ppp/secret +
/ppp/profile, never the hotspot objects.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import OperatorOwnedModel


class ServicePlan(OperatorOwnedModel):
    """A monthly broadband package. Separate from hotspot plans by design."""

    name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Monthly, KES")
    download_kbps = models.PositiveIntegerField()
    upload_kbps = models.PositiveIntegerField()
    # Optional MikroTik burst (all-or-nothing: set the trio to enable)
    burst_download_kbps = models.PositiveIntegerField(null=True, blank=True)
    burst_upload_kbps = models.PositiveIntegerField(null=True, blank=True)
    burst_threshold_download_kbps = models.PositiveIntegerField(null=True, blank=True)
    burst_threshold_upload_kbps = models.PositiveIntegerField(null=True, blank=True)
    burst_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    data_cap_gb = models.PositiveIntegerField(
        null=True, blank=True, help_text="Fair-use cap in GB; blank = unlimited"
    )
    mikrotik_profile = models.CharField(
        max_length=60, help_text="The /ppp/profile name pushed to the router"
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.name} (KSh {self.price}/mo)"

    @property
    def rate_limit(self) -> str:
        """MikroTik rate-limit string: rx/tx (upload/download from the client's
        perspective is tx/rx on the server; RouterOS rate-limit is tx/rx = up/down
        for the queue toward the client). We store up/down and format down/up as
        RouterOS expects rx-rate/tx-rate = client-download/client-upload... kept
        simple: 'UPk/DOWNk' with optional burst appended."""
        base = f"{self.upload_kbps}k/{self.download_kbps}k"
        if self.burst_download_kbps and self.burst_upload_kbps:
            base += (
                f" {self.burst_upload_kbps}k/{self.burst_download_kbps}k"
                f" {self.burst_threshold_upload_kbps or self.upload_kbps}k/"
                f"{self.burst_threshold_download_kbps or self.download_kbps}k"
                f" {self.burst_time_seconds or 8}/{self.burst_time_seconds or 8}"
            )
        return base


class Tower(OperatorOwnedModel):
    """A physical site/mast. Wireless clients connect to an AccessPoint on a tower."""

    name = models.CharField(max_length=80)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AccessPoint(OperatorOwnedModel):
    """A radio/sector on a tower. PTMP sectors serve many clients; PTP links one."""

    class Mode(models.TextChoices):
        AP = "ap", "AP (PTMP sector)"
        PTP = "ptp", "Point-to-point"
        PTMP = "ptmp", "Point-to-multipoint"

    tower = models.ForeignKey(Tower, on_delete=models.CASCADE, related_name="access_points")
    name = models.CharField(max_length=80)
    mode = models.CharField(max_length=6, choices=Mode.choices, default=Mode.AP)
    band = models.CharField(max_length=30, blank=True, help_text="e.g. 5GHz, 2.4GHz")
    frequency = models.CharField(max_length=30, blank=True)
    azimuth = models.PositiveSmallIntegerField(null=True, blank=True, help_text="degrees")
    capacity = models.PositiveSmallIntegerField(
        default=0, help_text="Max clients this AP should carry (0 = unset)"
    )
    router = models.ForeignKey(
        "provisioning.Router", null=True, blank=True, on_delete=models.SET_NULL
    )
    equipment = models.ForeignKey(
        "ops.Equipment", null=True, blank=True, on_delete=models.SET_NULL
    )
    ssid = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tower__name", "name"]

    def __str__(self):
        return f"{self.tower.name} / {self.name}"


class Client(OperatorOwnedModel):
    """A contracted broadband account set up by the ISP."""

    class Status(models.TextChoices):
        PENDING_INSTALL = "pending_install", "Pending installation"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended (overdue)"
        DISABLED = "disabled", "Disabled"

    class Delivery(models.TextChoices):
        FIBRE = "fibre", "Fibre"
        ETHERNET = "ethernet", "Ethernet"
        WIRELESS_PTP = "wireless_ptp", "Wireless PTP"
        WIRELESS_PTMP = "wireless_ptmp", "Wireless PTMP"

    # account_number is GLOBALLY unique: it is the C2B BillRefNumber on Danamo's
    # shared paybill, the only key that routes a payment to the right ISP+client.
    account_number = models.CharField(max_length=20, unique=True, db_index=True)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    physical_address = models.CharField(max_length=200, blank=True)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    plan = models.ForeignKey(ServicePlan, on_delete=models.PROTECT, related_name="clients")
    router = models.ForeignKey(
        "provisioning.Router", on_delete=models.PROTECT, related_name="pppoe_clients"
    )

    pppoe_username = models.CharField(max_length=60, unique=True)
    pppoe_password = models.CharField(max_length=60)
    static_ip = models.GenericIPAddressField(null=True, blank=True)

    delivery_method = models.CharField(
        max_length=15, choices=Delivery.choices, default=Delivery.FIBRE
    )
    access_point = models.ForeignKey(
        AccessPoint, null=True, blank=True, on_delete=models.SET_NULL, related_name="clients"
    )
    cpe_equipment = models.ForeignKey(
        "ops.Equipment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cpe_clients",
    )

    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING_INSTALL, db_index=True
    )
    billing_day = models.PositiveSmallIntegerField(default=1, help_text="Day of month, 1-28")
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Running credit; unpaid invoices reduce it",
    )
    next_due_date = models.DateField(null=True, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    ACTIVE_STATUSES = (Status.ACTIVE, Status.SUSPENDED)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operator", "status"])]

    def __str__(self):
        return f"{self.account_number} — {self.full_name}"

    @property
    def is_billable(self) -> bool:
        """Counts toward the platform per-user fee: a live service (active or
        merely suspended for non-payment), not pending-install or disabled."""
        return self.status in self.ACTIVE_STATUSES


class Invoice(OperatorOwnedModel):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="invoices")
    number = models.CharField(max_length=24, unique=True, db_index=True)
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.UNPAID, db_index=True
    )
    issued_at = models.DateTimeField(default=timezone.now)
    paid_at = models.DateTimeField(null=True, blank=True)

    OPEN_STATUSES = (Status.UNPAID, Status.OVERDUE)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            # one invoice per client per billing period
            models.UniqueConstraint(
                fields=["client", "period_start"], name="pppoe_invoice_unique_client_period"
            )
        ]

    def __str__(self):
        return f"{self.number} — {self.client.account_number} [{self.status}]"


# ---- helpers ---------------------------------------------------------------

_ACCOUNT_ALPHABET_DIGITS = "0123456789"


def generate_account_number(operator) -> str:
    """Globally-unique client account number. Prefix from the tenant slug so an
    ISP's numbers are recognisable, plus a random tail for global uniqueness on
    Danamo's shared paybill."""
    prefix = "".join(c for c in operator.slug.upper() if c.isalnum())[:4] or "WIF"
    for _ in range(10):
        tail = "".join(secrets.choice(_ACCOUNT_ALPHABET_DIGITS) for _ in range(5))
        candidate = f"{prefix}{tail}"
        if not Client.objects.filter(account_number=candidate).exists():
            return candidate
    raise RuntimeError("Could not allocate a unique account number")  # pragma: no cover


def default_next_due(billing_day: int, from_date=None):
    from_date = from_date or timezone.localdate()
    year, month = from_date.year, from_date.month
    # first upcoming occurrence of billing_day
    day = min(billing_day, 28)
    candidate = from_date.replace(day=day)
    if candidate <= from_date:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        candidate = candidate.replace(year=year, month=month, day=day)
    return candidate


def month_period(anchor):
    """The billing period starting at `anchor` (a client's billing day), one month."""
    year, month = anchor.year, anchor.month
    nm, ny = (month + 1, year) if month < 12 else (1, year + 1)
    day = min(anchor.day, 28)
    end = anchor.replace(year=ny, month=nm, day=day) - timedelta(days=1)
    return anchor, end
