import uuid

from django.conf import settings
from django.db import models

from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


class Voucher(OperatorOwnedModel):
    class Status(models.TextChoices):
        UNUSED = "unused", "Unused"
        REDEEMED = "redeemed", "Redeemed"
        EXPIRED = "expired", "Expired"
        VOID = "void", "Void"

    code = models.CharField(max_length=20, unique=True, db_index=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="vouchers")
    batch_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.UNUSED, db_index=True
    )
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    printed = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vouchers_created",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} [{self.status}]"
