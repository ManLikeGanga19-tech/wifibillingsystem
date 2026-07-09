"""Day-to-day ISP operations: support tickets, sales leads, expenses, equipment."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import OperatorOwnedModel
from apps.provisioning.models import Router


class Ticket(OperatorOwnedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    subject = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    subscriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_assigned",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_created",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.subject} [{self.status}]"


class Lead(OperatorOwnedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        CONVERTED = "converted", "Converted"
        LOST = "lost", "Lost"

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=120, blank=True)
    source = models.CharField(
        max_length=60, blank=True, help_text="How they found you, e.g. referral, flyer"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.NEW, db_index=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} [{self.status}]"


class Expense(OperatorOwnedModel):
    class Category(models.TextChoices):
        BANDWIDTH = "bandwidth", "Bandwidth / upstream"
        POWER = "power", "Power"
        RENT = "rent", "Site rent"
        SALARIES = "salaries", "Salaries"
        EQUIPMENT = "equipment", "Equipment"
        TRANSPORT = "transport", "Transport"
        OTHER = "other", "Other"

    date = models.DateField(default=timezone.localdate)
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    router = models.ForeignKey(
        Router,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Site this expense belongs to (optional)",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.description} KSh {self.amount}"


class Equipment(OperatorOwnedModel):
    class Type(models.TextChoices):
        ROUTER = "router", "Router"
        ANTENNA = "antenna", "Antenna"
        SWITCH = "switch", "Switch"
        CPE = "cpe", "CPE / client radio"
        CABLE = "cable", "Cabling"
        POWER = "power", "Power equipment"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        IN_STORE = "in_store", "In store"
        DEPLOYED = "deployed", "Deployed"
        FAULTY = "faulty", "Faulty"
        RETIRED = "retired", "Retired"

    name = models.CharField(max_length=120)
    equipment_type = models.CharField(max_length=10, choices=Type.choices, default=Type.OTHER)
    serial_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.IN_STORE, db_index=True
    )
    router = models.ForeignKey(
        Router,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Site where it is deployed (optional)",
    )
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "equipment"

    def __str__(self):
        return f"{self.name} [{self.status}]"
