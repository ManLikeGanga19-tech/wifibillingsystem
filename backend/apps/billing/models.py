"""Tenant wallets. All customer money lands on Danamo Tech's paybill; each sale
credits the ISP's wallet with commission withheld at source. Balance is the sum
of signed ledger amounts — no stored balance to drift out of sync."""

from django.conf import settings
from django.db import models

from apps.core.models import OperatorOwnedModel


class Settlement(models.TextChoices):
    """WHERE THE CASH ACTUALLY IS. Not the same question as "did they earn it".

    An ISP may sell through OUR paybill (money lands with us; we withhold commission and
    they withdraw the rest) or through THEIR OWN gateway (money lands with them, instantly;
    we never touch it and invoice our fee monthly).

    Both are real revenue and both belong in their reports. Only one of them is money we
    are holding on their behalf — and that is the only money they may withdraw.
    """

    PLATFORM = "platform", "Held by WIFI.OS"
    DIRECT = "direct", "Paid straight to the ISP"


class LedgerEntry(OperatorOwnedModel):
    class Type(models.TextChoices):
        SALE = "sale", "Sale (gross)"
        COMMISSION = "commission", "Platform commission"
        BASE_FEE = "base_fee", "Monthly platform fee"
        PPPOE_FEE = "pppoe_fee", "PPPoE per-user fee"
        SETUP_FEE = "setup_fee", "One-time setup fee"
        PAYOUT = "payout", "Payout withdrawal"
        SMS_CREDITS = "sms_credits", "SMS credits bought"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    entry_type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    # Signed: credits positive, debits negative. KES.
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # THE INVARIANT: an ISP may only withdraw money we are actually holding.
    #
    # Defaults to `platform` because that is what every entry written before the ISP could
    # bring their own gateway genuinely was — the money passed through us. A `direct` entry
    # records a sale whose cash went straight to the ISP's own account: it counts toward
    # their revenue and toward the fee they owe us, and it must NEVER count toward what
    # they can withdraw. See billing.services.withdrawable_balance.
    settlement = models.CharField(
        max_length=8,
        choices=Settlement.choices,
        default=Settlement.PLATFORM,
        db_index=True,
    )
    transaction = models.ForeignKey(
        "payments.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    payout = models.ForeignKey(
        "billing.Payout",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    # For periodic fees: "YYYY-MM" — uniqueness guard against double-charging a month
    period = models.CharField(max_length=7, blank=True)
    memo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operator", "created_at"])]
        constraints = [
            # one sale credit + one commission debit per transaction, never more
            models.UniqueConstraint(
                fields=["transaction", "entry_type"],
                condition=models.Q(transaction__isnull=False),
                name="ledger_unique_tx_entry_type",
            ),
            # one periodic fee per operator per month per type
            models.UniqueConstraint(
                fields=["operator", "entry_type", "period"],
                condition=~models.Q(period=""),
                name="ledger_unique_periodic_fee",
            ),
        ]

    def __str__(self):
        return f"{self.operator.slug} {self.entry_type} {self.amount}"


class Payout(OperatorOwnedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"

    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa (B2C, to a phone)"
        # The settlement rail: paybill -> paybill. This is the one an ISP with their
        # own shortcode uses, and it is also the account we KYC'd them against.
        PAYBILL = "paybill", "M-Pesa Paybill (B2B)"
        BANK = "bank", "Bank (EFT/Pesalink)"

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # max_length must fit the longest choice ("paybill" = 7).
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.MPESA)
    # M-Pesa destination
    phone = models.CharField(max_length=12, blank=True, help_text="M-Pesa number to pay")
    # Paybill destination (B2B) — the ISP's own shortcode
    paybill = models.CharField(max_length=20, blank=True)
    # Bank destination (paid manually now; the I&M H2H integration will execute
    # bank-method payouts automatically later)
    bank_name = models.CharField(max_length=80, blank=True)
    bank_account_number = models.CharField(max_length=40, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    # Reference of the actual transfer (M-Pesa code, or bank/Pesalink ref)
    mpesa_reference = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=200, blank=True)

    # The FIRST payout to an unconfirmed destination carries a code. The ISP reads it
    # back off their own statement, which proves the money actually landed where they
    # said it should — and costs us nothing, because it rides on money they asked for
    # anyway. Until it is confirmed, no SECOND payout leaves: that caps a wrong (or
    # hijacked) destination at one payout instead of an open drain.
    confirmation_code = models.CharField(max_length=16, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # Estimated payout cost the platform bears (M-Pesa B2C band / bank transfer).
    platform_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.operator.slug} payout KSh {self.amount} [{self.status}]"

    @property
    def destination(self) -> str:
        if self.method == self.Method.BANK:
            return f"{self.bank_name} · {self.bank_account_number} ({self.bank_account_name})"
        if self.method == self.Method.PAYBILL:
            return f"Paybill {self.paybill}"
        return self.phone
