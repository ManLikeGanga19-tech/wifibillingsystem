"""Loyalty points — reward subscribers for paying.

Points carry monetary value (they redeem for account credit), so they are a LIABILITY and
are modelled as a LEDGER, not a bare counter: every point traces to why it exists (a payment,
a redemption, an adjustment), and the balance is the sum of the ledger. `points_balance` on
the account is a denormalised cache kept in step with the ledger under the same lock — reads
are cheap, but the ledger is the truth.

Keyed by (operator, phone): one identity that covers hotspot subscribers today and PPPoE
clients later, all tenant-scoped — a customer's points with one ISP never touch another's.
"""

from django.db import models

from apps.core.models import Operator, OperatorOwnedModel


class LoyaltySettings(models.Model):
    """One ISP's loyalty programme configuration. Off by default — points are opt-in."""

    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="loyalty_settings"
    )
    is_enabled = models.BooleanField(default=False)

    # --- Earning ------------------------------------------------------------------------
    #: Points are awarded once per this much paid (KES). "Spend per point."
    spend_per_point = models.PositiveIntegerField(default=100)
    #: Points credited each time the spend threshold is crossed. "Points per threshold."
    points_per_threshold = models.PositiveIntegerField(default=1)

    # --- Redemption (rules stored now; the cash-in flow is the next phase) ---------------
    #: A subscriber must hold at least this many points before they can redeem.
    min_redeem_points = models.PositiveIntegerField(default=100)
    #: KES of account credit granted per point redeemed.
    value_per_point = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Loyalty settings for {self.operator.slug}"

    def points_for(self, amount) -> int:
        """Points earned on a payment of `amount` KES, per this ISP's rule."""
        if not self.spend_per_point:
            return 0
        crossings = int(amount) // self.spend_per_point
        return crossings * self.points_per_threshold


class LoyaltyAccount(OperatorOwnedModel):
    """A subscriber's points balance with ONE ISP, keyed by phone."""

    phone = models.CharField(max_length=12, db_index=True)
    points_balance = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "phone"], name="one_loyalty_account_per_operator_phone"
            )
        ]
        indexes = [models.Index(fields=["operator", "-points_balance"])]

    def __str__(self):
        return f"{self.phone}: {self.points_balance} pts @ {self.operator.slug}"


class LoyaltyLedgerEntry(OperatorOwnedModel):
    """One movement of points. Signed: earn is positive, redeem/expire negative."""

    class Kind(models.TextChoices):
        EARN = "earn", "Earned"
        REDEEM = "redeem", "Redeemed"
        ADJUST = "adjust", "Manual adjustment"
        EXPIRE = "expire", "Expired"

    account = models.ForeignKey(
        LoyaltyAccount, on_delete=models.CASCADE, related_name="entries"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)
    points = models.IntegerField(help_text="Signed: + earned, - redeemed")
    #: The payment that earned these points — also the idempotency key: one earn per payment.
    transaction = models.ForeignKey(
        "payments.Transaction", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="loyalty_entries",
    )
    reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One EARN per transaction — a replayed callback can't double-credit.
            models.UniqueConstraint(
                fields=["transaction"],
                condition=models.Q(kind="earn"),
                name="one_earn_per_transaction",
            )
        ]

    def __str__(self):
        return f"{self.kind} {self.points:+d} for {self.account.phone}"
