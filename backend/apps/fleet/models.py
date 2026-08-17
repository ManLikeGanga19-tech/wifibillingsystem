"""Technician fleet tracking — live positions for dispatch.

A signed-in technician's device streams its position; each fix is a TechLocationPing. The LIVE
fleet a dispatcher sees is the latest ping per technician; older pings are a short trail that a
nightly task prunes. Nothing is kept forever, everything is tenant-scoped, and a ping is only ever
written for the user who sent it (see the API).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import OperatorOwnedModel


class TechLocationPing(OperatorOwnedModel):
    """One reported position from a technician's device."""

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="location_pings"
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    #: Reported accuracy in metres — drives how wide the dot is drawn, so a poor fix reads as
    #: uncertainty rather than false precision.
    accuracy = models.PositiveIntegerField(null=True, blank=True)
    #: Direction of travel in degrees (0–360), when the device supplies it.
    heading = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    #: Server-stamped receipt time — indexed because every query is "latest per tech" or "older
    #: than the retention window", both keyed on this.
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [
            # The live-fleet query: newest ping per technician within one tenant.
            models.Index(fields=["operator", "technician", "-recorded_at"]),
        ]

    def __str__(self):
        return f"{self.technician_id} @ {self.recorded_at:%H:%M:%S}"
