"""Fleet housekeeping. Keeps the promise that there is no permanent movement archive."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import TechLocationPing


@shared_task
def prune_location_pings():
    """Delete technician location pings older than the retention window (default 24h). Runs
    nightly; the trail beyond the window simply ceases to exist."""
    cutoff = timezone.now() - timedelta(hours=settings.FLEET_RETENTION_HOURS)
    deleted, _ = TechLocationPing.objects.filter(recorded_at__lt=cutoff).delete()
    return {"deleted": deleted, "older_than_hours": settings.FLEET_RETENTION_HOURS}
