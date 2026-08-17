"""Graph walks over the fibre plant.

Spans are DIRECTED: from_point is the OLT-side (upstream), to_point is the customer-side
(downstream). "Downstream of X" therefore means following active spans from_point → to_point.
That's what a fault's blast radius is: X plus everything the light can no longer reach past it.
"""

from .models import FibrePoint, FibreSpan


def downstream_point_ids(point: FibrePoint) -> set[int]:
    """Every point reachable from `point` by following active spans away from the OLT — including
    `point` itself. Tenant-scoped and cycle-safe (a `seen` set), so a loop can't hang it."""
    seen = {point.id}
    frontier = [point.id]
    while frontier:
        current = frontier.pop()
        next_ids = (
            FibreSpan.objects.filter(
                operator_id=point.operator_id, is_active=True, from_point_id=current
            )
            .exclude(to_point_id__in=seen)
            .values_list("to_point_id", flat=True)
        )
        for nid in next_ids:
            seen.add(nid)
            frontier.append(nid)
    return seen


def affected_clients(point: FibrePoint):
    """The customers a fault at `point` takes offline: everyone whose ODP is `point` or any point
    downstream of it. This is the payoff of the Client.fibre_point link."""
    from apps.pppoe.models import Client

    return (
        Client.objects.filter(
            operator_id=point.operator_id,
            fibre_point_id__in=downstream_point_ids(point),
        )
        .select_related("plan")
        .order_by("full_name")
    )
