from decimal import Decimal

from django.conf import settings
from django.db import models

from .fields import EncryptedTextField


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Operator(TimeStampedModel):
    """The tenant: one WISP business, resolved from the <slug> subdomain."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    is_active = models.BooleanField(default=True)  # hard kill-switch, distinct from status
    approved_at = models.DateTimeField(null=True, blank=True)

    # Contact (the ISP owner)
    owner_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)

    # Per-operator M-Pesa credentials. Blank means "use the env-var defaults" (pilot).
    mpesa_shortcode = models.CharField(max_length=20, blank=True)
    mpesa_passkey = EncryptedTextField(blank=True)
    daraja_consumer_key = EncryptedTextField(blank=True)
    daraja_consumer_secret = EncryptedTextField(blank=True)

    # Danamo Tech's own WISP: charges itself nothing. Guarded so rates can't be
    # fat-fingered back on.
    is_platform_owned = models.BooleanField(
        default=False,
        help_text="Platform's own ISP: exempt from all commission and platform fees.",
    )

    # Saved payout destinations (the ISP fills these once; the wallet withdraw
    # form pre-fills from them). Bank payouts are executed manually now, and by
    # the I&M H2H integration later.
    payout_phone = models.CharField(max_length=12, blank=True)
    payout_bank_name = models.CharField(max_length=80, blank=True)
    payout_bank_account_number = models.CharField(max_length=40, blank=True)
    payout_bank_account_name = models.CharField(max_length=120, blank=True)

    # Platform billing rates (editable per tenant from the platform portal)
    base_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Flat KSh/month for the subdomain"
    )
    hotspot_commission_pct = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("3.00"),
        help_text="% of hotspot revenue",
    )
    pppoe_user_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="KSh per active PPPoE user/month"
    )

    RESERVED_SLUGS = {
        "www", "api", "admin", "portal", "app", "mail", "platform", "billing",
        "status", "docs", "static", "media",
    }

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def is_operational(self) -> bool:
        return self.is_active and self.status == self.Status.ACTIVE

    @property
    def effective_commission_pct(self) -> Decimal:
        """0% for the platform's own ISP — Danamo does not bill itself."""
        if self.is_platform_owned:
            return Decimal("0.00")
        return Decimal(str(self.hotspot_commission_pct))

    @property
    def effective_base_fee(self) -> Decimal:
        if self.is_platform_owned:
            return Decimal("0.00")
        return Decimal(str(self.base_fee))

    @property
    def has_mpesa_credentials(self) -> bool:
        return bool(self.mpesa_shortcode and self.daraja_consumer_key)


class OperatorOwnedModel(TimeStampedModel):
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="%(class)ss"
    )

    class Meta:
        abstract = True


class AuditLog(models.Model):
    operator = models.ForeignKey(Operator, null=True, blank=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.target_type}#{self.target_id}"
