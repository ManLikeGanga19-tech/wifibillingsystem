"""Sector capacity: the soft warning when an ISP over-subscribes an access point.

A PPPoE client attaches to an AccessPoint (a sector on a tower). Each sector has a capacity
— the number of clients it should carry before it congests. Going over is sometimes a
deliberate call an ISP makes, so this is a WARNING, not a hard block: the API refuses ONCE
with a 409 + a warning payload, and a re-submit with force=True goes through and is AUDITED.
That records that the ISP was warned and chose to proceed — so the over-subscription is on
their books, not ours.

The count matches the AccessPoint list's `client_count` (active + suspended clients occupy a
slot), so the number in the warning is the same number the console shows on the sector.
"""

from .models import AccessPoint, Client


def _active_on(operator, access_point, *, exclude_pk=None) -> int:
    qs = Client.objects.filter(
        operator=operator,
        access_point=access_point,
        status__in=Client.ACTIVE_STATUSES,
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def capacity_warning(operator, access_point, *, exclude_pk=None) -> dict | None:
    """None if the sector has room (or no capacity is set); otherwise the warning payload the
    console renders. `exclude_pk` lets an edit/move not count the client against itself.

    Computed on the LIVE count under the caller's request, so two admins racing for the last
    slot both see the sector as full."""
    if access_point is None or not access_point.capacity:
        return None

    count = _active_on(operator, access_point, exclude_pk=exclude_pk)
    if count < access_point.capacity:
        return None

    # Tower context — the sector is the hard trigger, but the ISP wants to see how loaded the
    # whole site is. Aggregate across the tower's sectors that HAVE a capacity set.
    tower = access_point.tower
    sectors = AccessPoint.objects.filter(operator=operator, tower=tower, capacity__gt=0)
    tower_capacity = sum(s.capacity for s in sectors)
    tower_count = Client.objects.filter(
        operator=operator,
        access_point__tower=tower,
        status__in=Client.ACTIVE_STATUSES,
    ).count()
    tower_util = round(100 * tower_count / tower_capacity) if tower_capacity else None

    return {
        "code": "sector_at_capacity",
        "detail": f"{access_point.name} is at full capacity.",
        "sector": access_point.name,
        "count": count,
        "capacity": access_point.capacity,
        "tower": tower.name,
        "tower_utilization": tower_util,
    }
