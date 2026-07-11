import uuid

from django.db import models

from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


class Transaction(OperatorOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        TIMEOUT = "timeout", "Timeout"
        RECONCILED = "reconciled", "Success (reconciled)"

    # Public UUID so the portal can poll status without exposing sequential IDs
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    subscriber = models.ForeignKey(
        "accounts.Subscriber",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="transactions")
    router = models.ForeignKey(
        "provisioning.Router", null=True, blank=True, on_delete=models.SET_NULL
    )
    phone = models.CharField(max_length=12, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    account_reference = models.CharField(max_length=20, blank=True)
    mac_address = models.CharField(max_length=17, blank=True)

    checkout_request_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    reconcile_attempts = models.PositiveSmallIntegerField(default=0)

    SUCCESS_STATUSES = (Status.SUCCESS, Status.RECONCILED)
    TERMINAL_STATUSES = (Status.SUCCESS, Status.RECONCILED, Status.FAILED, Status.TIMEOUT)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.phone} KSh {self.amount} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


class C2BPayment(models.Model):
    """A paybill (C2B) payment received on Danamo's shortcode — how PPPoE clients
    pay. The BillRefNumber is the client's globally-unique account number, which
    routes the money to the right ISP + client. Idempotent on M-Pesa TransID."""

    class Status(models.TextChoices):
        MATCHED = "matched", "Matched to a client"
        UNMATCHED = "unmatched", "No matching account"

    trans_id = models.CharField(max_length=30, unique=True, db_index=True)
    bill_ref = models.CharField(max_length=30, db_index=True, help_text="Account number typed")
    msisdn = models.CharField(max_length=15, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    first_name = models.CharField(max_length=60, blank=True)
    # Set when matched; operator derived from the client
    operator = models.ForeignKey(
        "core.Operator", null=True, blank=True, on_delete=models.SET_NULL
    )
    client = models.ForeignKey(
        "pppoe.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"C2B {self.trans_id} {self.bill_ref} KSh {self.amount} [{self.status}]"
