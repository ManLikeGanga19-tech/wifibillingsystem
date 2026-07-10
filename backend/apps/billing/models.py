"""Tenant wallets. All customer money lands on Danamo Tech's paybill; each sale
credits the ISP's wallet with commission withheld at source. Balance is the sum
of signed ledger amounts — no stored balance to drift out of sync."""

from django.conf import settings
from django.db import models

from apps.core.models import OperatorOwnedModel


class LedgerEntry(OperatorOwnedModel):
    class Type(models.TextChoices):
        SALE = "sale", "Sale (gross)"
        COMMISSION = "commission", "Platform commission"
        BASE_FEE = "base_fee", "Monthly platform fee"
        PPPOE_FEE = "pppoe_fee", "PPPoE per-user fee"
        PAYOUT = "payout", "Payout withdrawal"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    entry_type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    # Signed: credits positive, debits negative. KES.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
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

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    phone = models.CharField(max_length=12, help_text="M-Pesa number to pay")
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
    mpesa_reference = models.CharField(max_length=30, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.operator.slug} payout KSh {self.amount} [{self.status}]"
