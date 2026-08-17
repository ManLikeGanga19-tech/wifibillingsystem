"""Fibre outside-plant (ADSS) — the physical fibre network as a graph.

Parallel to the wireless topology (Tower → AccessPoint → Client): a FibrePoint is a NODE (OLT,
splitter, ODP, splice closure, pole, handhole…), a FibreSpan is an EDGE (a cable run between two
points), and a fibre customer hangs off the ODP that feeds them (Client.fibre_point). Rooted at
the OLT, the graph lets us trace a customer's fibre path and read the blast radius of a fault.

Everything is tenant-scoped (OperatorOwnedModel). Deletes are SOFT (is_active) so real plant
history and customer links survive — plant that took a crew a day to record is never one click
from gone.
"""

from django.conf import settings
from django.db import models

from apps.core.models import OperatorOwnedModel


class PlantStatus(models.TextChoices):
    """Shared by points and spans; maps 1:1 to the map's green/amber/red."""

    OK = "ok", "OK"
    NEEDS_ATTENTION = "needs_attention", "Needs attention"
    DOWN = "down", "Down"


class FibrePoint(OperatorOwnedModel):
    """A node in the fibre plant — where cable terminates, splits, joins, or is supported."""

    class Type(models.TextChoices):
        OLT_POP = "olt_pop", "OLT / POP"
        CABINET = "cabinet", "Cabinet (FDT)"
        SPLICE_CLOSURE = "splice_closure", "Splice closure"
        SPLITTER = "splitter", "Splitter"
        ODP = "odp", "ODP"
        POLE = "pole", "Pole"
        HANDHOLE = "handhole", "Handhole"
        OTHER = "other", "Other"

    class SplitterRatio(models.TextChoices):
        R1_2 = "1:2", "1:2"
        R1_4 = "1:4", "1:4"
        R1_8 = "1:8", "1:8"
        R1_16 = "1:16", "1:16"
        R1_32 = "1:32", "1:32"
        R1_64 = "1:64", "1:64"

    #: Points that CARRY customer drops (their port_capacity is meaningful). A pole/closure/
    #: handhole is structural — capacity is n/a there.
    PORTED_TYPES = (Type.ODP, Type.SPLITTER, Type.CABINET)

    type = models.CharField(max_length=20, choices=Type.choices, default=Type.ODP, db_index=True)
    label = models.CharField(max_length=80)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=PlantStatus.choices, default=PlantStatus.OK, db_index=True
    )
    # Total drops/cores this point can carry. 0 = not applicable / unset. "used" is NEVER stored —
    # it is counted live from the customer drops on this point (see the API), so it can't drift.
    port_capacity = models.PositiveSmallIntegerField(default=0)
    splitter_ratio = models.CharField(max_length=5, choices=SplitterRatio.choices, blank=True)
    notes = models.TextField(blank=True)
    #: Soft-delete: "delete" flips this off; the row and its links survive and can be restored.
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["type", "label"]
        indexes = [models.Index(fields=["operator", "is_active"])]

    def __str__(self):
        return f"{self.get_type_display()} {self.label}"


class FibreSpan(OperatorOwnedModel):
    """A cable run (edge) between two FibrePoints — the drawn route on the map."""

    class Cable(models.TextChoices):
        ADSS = "adss", "ADSS (aerial)"
        BURIED = "buried", "Buried"
        DROP = "drop", "Drop"

    # PROTECT, not CASCADE: points are soft-deleted (never hard-deleted), so a span is never
    # silently swept away with a point. If a hard delete is ever attempted, it fails loudly.
    from_point = models.ForeignKey(FibrePoint, on_delete=models.PROTECT, related_name="spans_out")
    to_point = models.ForeignKey(FibrePoint, on_delete=models.PROTECT, related_name="spans_in")
    cable_type = models.CharField(max_length=8, choices=Cable.choices, default=Cable.ADSS)
    fibre_count = models.PositiveSmallIntegerField(default=0, help_text="Cores in this cable")
    length_m = models.PositiveIntegerField(null=True, blank=True, help_text="Run length, metres")
    status = models.CharField(
        max_length=16, choices=PlantStatus.choices, default=PlantStatus.OK, db_index=True
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A cable can't run from a point to itself.
            models.CheckConstraint(
                check=~models.Q(from_point=models.F("to_point")),
                name="fibre_span_no_self_loop",
            ),
        ]
        indexes = [models.Index(fields=["operator", "is_active"])]

    def __str__(self):
        return f"{self.from_point_id}→{self.to_point_id} ({self.cable_type})"
