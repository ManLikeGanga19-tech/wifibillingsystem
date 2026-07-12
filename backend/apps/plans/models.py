from django.db import models

from apps.core.models import OperatorOwnedModel


class Plan(OperatorOwnedModel):
    class PlanType(models.TextChoices):
        HOTSPOT = "hotspot", "Hotspot (prepaid)"
        PPPOE = "pppoe", "PPPoE (monthly)"  # Phase 2

    name = models.CharField(max_length=80)
    plan_type = models.CharField(
        max_length=10, choices=PlanType.choices, default=PlanType.HOTSPOT
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)  # KES
    duration = models.DurationField(help_text="Access time granted, e.g. 1:00:00 for one hour")
    data_cap_mb = models.PositiveIntegerField(
        null=True, blank=True, help_text="Blank = unlimited data"
    )
    download_kbps = models.PositiveIntegerField()
    upload_kbps = models.PositiveIntegerField()
    shared_users = models.PositiveSmallIntegerField(default=1)
    mikrotik_profile = models.CharField(
        max_length=60, default="default", help_text="Hotspot user profile name on the router"
    )
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.name} (KSh {self.price})"

    @property
    def duration_seconds(self) -> int:
        return int(self.duration.total_seconds())

    @property
    def rate_limit(self) -> str:
        """MikroTik rate-limit string for the hotspot user: rx/tx = upload/download,
        same convention as PPPoE (ServicePlan.rate_limit). Set on the user directly so
        speed is enforced per session, not left to a hand-made profile on the router."""
        return f"{self.upload_kbps}k/{self.download_kbps}k"
