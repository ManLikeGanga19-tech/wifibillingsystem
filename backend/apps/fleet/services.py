"""Dispatch maths: who's the closest technician to a fault.

Straight-line (haversine) distance for v1 — an honest "closest as the crow flies", not drive-time.
Real routing (self-hosted OSRM drive-time) is a later phase and slots in behind nearest_technicians.
"""

import math
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import TechLocationPing

_EARTH_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlmb = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def latest_pings(operator):
    """The newest ping per technician for one tenant (Postgres DISTINCT ON)."""
    return (
        TechLocationPing.objects.filter(operator=operator)
        .order_by("technician_id", "-recorded_at")
        .distinct("technician_id")
        .select_related("technician")
    )


def nearest_technicians(operator, lat, lng, live_only=True):
    """(ping, distance_km) for each technician, nearest first. `live_only` drops anyone whose last
    fix is older than the live window — you can't dispatch a tech who went dark."""
    cutoff = timezone.now() - timedelta(minutes=settings.FLEET_LIVE_MINUTES)
    ranked = []
    for ping in latest_pings(operator):
        if live_only and ping.recorded_at < cutoff:
            continue
        ranked.append((ping, haversine_km(lat, lng, ping.lat, ping.lng)))
    ranked.sort(key=lambda pair: pair[1])
    return ranked
