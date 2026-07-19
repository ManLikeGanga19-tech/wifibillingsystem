"""Tenant wallets. All customer money lands on Danamo Tech's paybill; each sale
credits the ISP's wallet with commission withheld at source. Balance is the sum
of signed ledger amounts — no stored balance to drift out of sync."""

from decimal import Decimal

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
    # Paybill destination (B2B) — the ISP's own shortcode + the account to credit at it
    paybill = models.CharField(max_length=20, blank=True)
    paybill_account = models.CharField(max_length=40, blank=True)
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
    def net_amount(self) -> Decimal:
        """What actually reaches the ISP: the requested amount MINUS the transfer cost the ISP
        bears. The wallet is debited the full `amount`; the cost is remitted to the rail
        (Safaricom / the bank), so this is the figure the payout transfer sends."""
        return self.amount - (self.platform_cost or Decimal("0"))

    @property
    def destination(self) -> str:
        if self.method == self.Method.BANK:
            return f"{self.bank_name} · {self.bank_account_number} ({self.bank_account_name})"
        if self.method == self.Method.PAYBILL:
            acct = f" acct {self.paybill_account}" if self.paybill_account else ""
            return f"Paybill {self.paybill}{acct}"
        return self.phone


class PlatformLedgerEntry(OperatorOwnedModel):
    """The ISP's account WITH US. Not to be confused with the wallet above.

    Two different relationships, and keeping them apart is the point:

      * LedgerEntry (the wallet)  — money we HOLD FOR the ISP. They withdraw it.
      * PlatformLedgerEntry       — money the ISP OWES US, or has prepaid to us.

    Denominated in KES and signed, and the balance is the SUM — never a stored counter,
    for the same reason as the wallet: a counter decremented twice on a retry silently
    robs somebody, and no one can prove it afterwards.

    A NEGATIVE balance is normal: this is postpaid. Fees accrue as they happen and are
    invoiced monthly; the ISP settles by STK push, which credits it back toward zero.
    """

    class Reason(models.TextChoices):
        TOPUP = "topup", "Top-up (STK)"
        GRANT = "grant", "Granted by the platform"
        SMS = "sms", "SMS sent"
        COMMISSION = "commission", "Commission on a direct-settled sale"
        BASE_FEE = "base_fee", "Monthly platform fee"
        PPPOE_FEE = "pppoe_fee", "PPPoE per-user fee"
        SETUP_FEE = "setup_fee", "One-time onboarding fee"
        REFUND = "refund", "Refund"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    #: Signed KES. Credits (top-ups, grants) positive; charges (SMS, fees) negative.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=12, choices=Reason.choices, db_index=True)

    #: The SMS this charge paid for. Unique, so a retried Celery task cannot bill the ISP
    #: twice for one message.
    message = models.ForeignKey(
        "notifications.Message",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_charges",
    )
    topup = models.ForeignKey(
        "billing.TopUp",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    #: The sale this fee is the commission ON. Unique, so the commission on a DIRECT sale is
    #: charged exactly once however many times a replayed callback lands.
    transaction = models.ForeignKey(
        "payments.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_fees",
    )
    #: "YYYY-MM" for periodic fees — the uniqueness guard against double-charging a month.
    period = models.CharField(max_length=7, blank=True)
    memo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operator", "created_at"])]
        constraints = [
            # One charge per message, however many times the send task retries.
            models.UniqueConstraint(
                fields=["message"],
                condition=models.Q(message__isnull=False),
                name="platform_one_charge_per_message",
            ),
            # One credit per top-up, however many times Safaricom replays the callback.
            models.UniqueConstraint(
                fields=["topup"],
                condition=models.Q(topup__isnull=False),
                name="platform_one_credit_per_topup",
            ),
            # One commission per direct sale, however many times the callback replays.
            models.UniqueConstraint(
                fields=["transaction"],
                condition=models.Q(transaction__isnull=False),
                name="platform_one_commission_per_sale",
            ),
            # One periodic fee per operator per month per type.
            models.UniqueConstraint(
                fields=["operator", "reason", "period"],
                condition=~models.Q(period=""),
                name="platform_unique_periodic_fee",
            ),
        ]

    def __str__(self):
        return f"{self.operator.slug} {self.reason} {self.amount:+}"


class TopUp(OperatorOwnedModel):
    """An ISP paying US, by STK push to Danamo's paybill.

    This is the ISP's own money coming to us — it is NOT a subscriber payment and must
    never be confused with one (a subscriber payment credits the ISP; this debits them).
    Hence its own model and its own callback URL, rather than riding on Transaction.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting the customer's PIN"
        SUCCESS = "success", "Paid"
        FAILED = "failed", "Failed or cancelled"
        TIMEOUT = "timeout", "No response from M-Pesa"

    #: What they paid.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    #: What we credit — may EXCEED `amount`: the volume bundles give bonus credit, which
    #: is how a per-SMS discount is expressed in a shilling-denominated balance.
    credit = models.DecimalField(max_digits=10, decimal_places=2)
    bundle = models.CharField(max_length=20, blank=True)

    phone = models.CharField(max_length=12)
    # NULL until Daraja answers with one. Nullable rather than blank because Postgres
    # permits many NULLs in a unique index but only ONE empty string — two ISPs starting a
    # top-up at the same instant would otherwise collide on "".
    checkout_request_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, default=None
    )
    merchant_request_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    mpesa_receipt = models.CharField(max_length=32, blank=True)
    result_desc = models.CharField(max_length=200, blank=True)
    #: Stored verbatim BEFORE parsing — the record of what Safaricom actually said.
    raw_callback = models.JSONField(null=True, blank=True)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    reconcile_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.operator.slug} top-up KSh {self.amount} [{self.status}]"


class PlatformInvoice(OperatorOwnedModel):
    """The ISP's monthly statement from WIFI.OS — what we charged THEM.

    Not to be confused with pppoe.Invoice (what a broadband SUBSCRIBER owes the ISP). This
    is the other direction: what the ISP owes US.

    A STATEMENT, not a fresh charge. The fees were already accrued to the platform account
    as they happened (billing.services), and enforcement already runs on the live balance.
    This snapshots a month so the ISP has a formal, itemised record — every fee visible,
    however the underlying sale settled, so nothing goes unnoticed.

    `withheld_commission` is shown for completeness and marked "already deducted": on an
    aggregator sale we took our cut at source, so it is not money owed — but it belongs on
    the statement so the picture is whole.
    """

    class Status(models.TextChoices):
        OUTSTANDING = "outstanding", "Outstanding"
        PAID = "paid", "Paid"

    period = models.CharField(max_length=7, help_text="YYYY-MM")
    issued_at = models.DateTimeField(auto_now_add=True)

    # The period's fees, itemised. All positive amounts (what we charged).
    base_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pppoe_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    setup_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    #: Commission on the ISP's OWN-gateway sales — money DUE (we could not withhold it).
    direct_commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sms = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    #: Aggregator commission, ALREADY taken at source. Informational, not part of the total.
    withheld_commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    #: The fees this statement charges = everything except the already-withheld commission.
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OUTSTANDING, db_index=True
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period"]
        constraints = [
            # One statement per operator per month, ever — a re-run of the beat task is a
            # no-op, never a duplicate bill.
            models.UniqueConstraint(
                fields=["operator", "period"], name="one_platform_invoice_per_month"
            )
        ]

    def __str__(self):
        return f"{self.operator.slug} statement {self.period} KSh {self.total} [{self.status}]"
