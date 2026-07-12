from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


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

    # Captured at signup
    county = models.CharField(max_length=40, blank=True, help_text="County of operation")
    referral_source = models.CharField(
        max_length=40, blank=True, help_text="How they heard about us"
    )

    # NOTE: there are deliberately NO per-ISP Daraja/collection credentials here.
    # Customers NEVER pay an ISP directly — every shilling lands on Danamo's own
    # paybill and is attributed to the ISP in the ledger (DarajaClient ignores the
    # operator entirely). Fields implying otherwise used to exist and were actively
    # misleading: they are what made the suspended-pay page tell a subscriber to pay
    # the ISP's shortcode, where we would never have seen the money.

    # Danamo Tech's own WISP: charges itself nothing. Guarded so rates can't be
    # fat-fingered back on.
    is_platform_owned = models.BooleanField(
        default=False,
        help_text="Platform's own ISP: exempt from all commission and platform fees.",
    )

    # ---- SETTLEMENT: where WE pay THEM ---------------------------------------
    # This is an OUTBOX, not a collection account. It is also our KYC bar: to hold a
    # paybill or a business bank account, Safaricom/the bank already ran full KYC on
    # this business — so we inherit it for free. A shell company cannot produce one.
    class Settlement(models.TextChoices):
        PAYBILL = "paybill", "M-Pesa Paybill (B2B)"
        BANK = "bank", "Bank account (Pesalink/EFT)"

    settlement_method = models.CharField(
        max_length=8, choices=Settlement.choices, blank=True
    )
    settlement_paybill = models.CharField(
        max_length=20, blank=True, help_text="Their OWN paybill — we send money TO it"
    )
    settlement_name = models.CharField(
        max_length=120, blank=True, help_text="Registered name on the account"
    )
    payout_bank_name = models.CharField(max_length=80, blank=True)
    payout_bank_account_number = models.CharField(max_length=40, blank=True)
    payout_bank_account_name = models.CharField(max_length=120, blank=True)
    # Legacy M-Pesa-phone payout destination (kept for existing tenants).
    payout_phone = models.CharField(max_length=12, blank=True)

    # ---- Proof they actually CONTROL that account ----------------------------
    # Anyone can type "123456". So we prove it the way banks do: send a few
    # shillings carrying a random reference, and ask them to read it back. Cannot be
    # faked without access to the account's own statement.
    settlement_verified_at = models.DateTimeField(null=True, blank=True)
    verification_ref = models.CharField(max_length=16, blank=True)
    verification_amount = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    verification_sent_at = models.DateTimeField(null=True, blank=True)
    verification_attempts = models.PositiveSmallIntegerField(default=0)

    # Platform billing rates (editable per tenant from the platform portal).
    # Model: 1-month free trial, then KES 500 base + 3% hotspot + per-PPPoE-user
    # (Centipid-matched flat rate via apps.billing.pricing) + an OPT-IN one-time
    # setup fee for assisted onboarding.
    base_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("500.00"),
        help_text="Flat KSh/month for the subdomain (waived during the free trial)",
    )
    # First month free: no base fee is charged on or before this date. Set when
    # the ISP is approved. Null = no trial (legacy/seeded tenants).
    trial_ends_at = models.DateField(
        null=True, blank=True, help_text="Base fee is waived up to and including this date"
    )
    hotspot_commission_pct = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("3.00"),
        help_text="% of hotspot revenue",
    )
    # 0 = use the platform's graduated tier table (billing.pricing); a positive
    # value is a custom flat rate negotiated with this ISP (overrides the tiers).
    pppoe_user_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="KSh per active PPPoE user/month; 0 = use platform volume tiers",
    )
    setup_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("10000.00"),
        help_text="One-time onboarding fee, billed once when the ISP is approved",
    )

    RESERVED_SLUGS = {
        "www", "api", "admin", "portal", "app", "mail", "platform", "billing",
        "status", "docs", "static", "media", "signup", "signin", "help", "support",
        "blog", "pricing", "about",
    }

    class Meta:
        constraints = [
            # Daniel: "no duplicate slugs OR company names". The slug already has a
            # unique index; this makes the NAME unique too, case-insensitively —
            # "Homelink" and "homelink" are the same business.
            #
            # The signup wizard checks availability as you type, but that check is
            # only advisory: between step 3 and step 5 someone else can take it.
            # THIS is the referee. The service catches the IntegrityError and sends
            # them back to rename.
            models.UniqueConstraint(
                Lower("name"), name="operator_name_unique_ci"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    # ---- THE TWO GATES ------------------------------------------------------
    # "Can you USE the console?" and "Can MONEY move?" are different questions, and
    # conflating them was the old design. A freshly signed-up ISP gets their console
    # immediately (add routers, plans, branding — real work, real momentum) but
    # cannot take a single shilling until we have verified who they are.
    #
    # That gate is not bureaucracy: WE hold the paybill. An unverified business
    # collecting real customer money through Danamo's shortcode is our AML problem,
    # not theirs. See docs/ONBOARDING_ARCHITECTURE.md §3.

    @property
    def is_operational(self) -> bool:
        """May their staff open the console at all?

        PENDING is allowed — that is the whole point of "explore now, money later".
        SUSPENDED is not: that is a door we have deliberately shut.
        """
        return self.is_active and self.status != self.Status.SUSPENDED

    @property
    def can_transact(self) -> bool:
        """May money move for this ISP — collect, provision, or withdraw?

        Two independent conditions, and BOTH must hold:
          1. ACTIVE (not pending, not suspended, not killed)
          2. a VERIFIED settlement account — we have proved they control the
             paybill/bank we would pay them into

        (2) is defence in depth on purpose. Verification is what flips them ACTIVE
        in the first place, so it should be redundant — but if anyone ever sets
        status=active by hand, in the admin or straight in the database, money still
        does not move for a business we have not proved out. The gate does not
        depend on one flag being right.

        Danamo's own WISP is exempt: settling to ourselves is meaningless.
        """
        if not (self.is_active and self.status == self.Status.ACTIVE):
            return False
        if self.is_platform_owned:
            return True
        return self.settlement_verified_at is not None

    @property
    def has_settlement_account(self) -> bool:
        if self.settlement_method == self.Settlement.PAYBILL:
            return bool(self.settlement_paybill)
        if self.settlement_method == self.Settlement.BANK:
            return bool(self.payout_bank_name and self.payout_bank_account_number)
        return False

    @property
    def settlement_destination(self) -> str:
        if self.settlement_method == self.Settlement.PAYBILL:
            return f"Paybill {self.settlement_paybill} ({self.settlement_name})"
        if self.settlement_method == self.Settlement.BANK:
            return (
                f"{self.payout_bank_name} · {self.payout_bank_account_number} "
                f"({self.payout_bank_account_name})"
            )
        return ""

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
    def effective_setup_fee(self) -> Decimal:
        if self.is_platform_owned:
            return Decimal("0.00")
        return Decimal(str(self.setup_fee))

    def in_base_fee_trial(self, on_date=None) -> bool:
        """True while the first-month free trial covers the base fee."""
        if not self.trial_ends_at:
            return False
        from django.utils import timezone

        on_date = on_date or timezone.localdate()
        return on_date <= self.trial_ends_at



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
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operator", "-created_at"])]

    def __str__(self):
        return f"{self.action} {self.target_type}#{self.target_id}"


class ImpersonationGrant(models.Model):
    """Platform staff entering an ISP's console ("view as") is a PRIVILEGED,
    RECORDED act — never a silent header flip.

    Danamo holds other people's money, so walking into a tenant's console must be
    deliberate, justified, time-boxed, and permanently recorded. `acting_tenant()`
    refuses to resolve a foreign tenant without a live grant, so this model is the
    only door in. A platform user's OWN operator needs no grant.
    """

    DEFAULT_MINUTES = 60

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonations"
    )
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="impersonations"
    )
    reason = models.CharField(max_length=200, help_text="Why this access was needed")
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Explicitly exited")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["actor", "operator", "expires_at"])]

    def __str__(self):
        return f"{self.actor} -> {self.operator.slug} ({self.reason})"

    @property
    def is_live(self) -> bool:
        from django.utils import timezone

        return self.ended_at is None and self.expires_at > timezone.now()
