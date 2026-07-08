import uuid

from django.conf import settings
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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
