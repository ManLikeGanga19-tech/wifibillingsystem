"""Graph walks over the fibre plant.

Spans are DIRECTED: from_point is the OLT-side (upstream), to_point is the customer-side
(downstream). "Downstream of X" therefore means following active spans from_point → to_point.
That's what a fault's blast radius is: X plus everything the light can no longer reach past it.

Routing (shortest_path) is the mirror image: to physically WALK the cable between two points you
can traverse a span either way, so the routing graph is UNDIRECTED even though blast-radius is
directed. Weight is the run length in metres.
"""

import heapq
import math

from .models import FibrePoint, FibreSpan


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in metres between two lat/lng pairs (floats)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_point(operator_id: int, lat: float, lng: float):
    """The placed plant point closest (great-circle) to an arbitrary coordinate — how a field
    user's GPS 'snaps' onto the plant so we can route from where they are standing. Returns
    (FibrePoint, distance_m) or (None, None) when the tenant has no placed points."""
    best, best_d = None, None
    for p in (
        FibrePoint.objects.filter(operator_id=operator_id, is_active=True)
        .exclude(gps_lat__isnull=True).exclude(gps_lng__isnull=True)
        .only("id", "label", "type", "gps_lat", "gps_lng")
    ):
        d = _haversine_m(lat, lng, float(p.gps_lat), float(p.gps_lng))
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best, best_d


def _edge_weight(length_m, a, b) -> float:
    """Metres to cross a span. Prefer the recorded run length; fall back to the straight-line
    distance between its endpoints when length wasn't captured, so a route always has a cost and
    the shortest one is still meaningful. `a`/`b` are (lat, lng) floats or None."""
    if length_m:
        return float(length_m)
    if a and b:
        return _haversine_m(a[0], a[1], b[0], b[1])
    return 1000.0  # unknown length, no coords: a neutral non-zero cost so it's never "free"


def shortest_path(operator_id: int, from_point_id: int, to_point_id: int):
    """Dijkstra over this tenant's active plant, shortest total cable length from one point to
    another. Returns a dict {points, spans, total_m, span_count, splice_count} or None when the
    two points aren't connected. The whole plant is two queries; plants are small, so this is
    microseconds even for the largest.
    """
    if from_point_id == to_point_id:
        p = FibrePoint.objects.filter(operator_id=operator_id, id=from_point_id).first()
        if not p:
            return None
        return {"points": [p], "spans": [], "total_m": 0.0, "span_count": 0, "splice_count": 0}

    points = {
        p.id: p
        for p in FibrePoint.objects.filter(operator_id=operator_id, is_active=True)
        .only("id", "label", "type", "gps_lat", "gps_lng")
    }
    if from_point_id not in points or to_point_id not in points:
        return None

    def coord(pid):
        p = points[pid]
        if p.gps_lat is None or p.gps_lng is None:
            return None
        return (float(p.gps_lat), float(p.gps_lng))

    # Undirected adjacency: {pid: [(neighbour, weight, span_id), ...]}.
    adj: dict[int, list[tuple[int, float, int]]] = {pid: [] for pid in points}
    for s in FibreSpan.objects.filter(operator_id=operator_id, is_active=True).only(
        "id", "from_point_id", "to_point_id", "length_m"
    ):
        if s.from_point_id not in points or s.to_point_id not in points:
            continue
        w = _edge_weight(s.length_m, coord(s.from_point_id), coord(s.to_point_id))
        adj[s.from_point_id].append((s.to_point_id, w, s.id))
        adj[s.to_point_id].append((s.from_point_id, w, s.id))

    # Classic Dijkstra with a lazy heap; prev remembers the (point, span) we arrived by.
    dist = {from_point_id: 0.0}
    prev: dict[int, tuple[int, int]] = {}
    heap = [(0.0, from_point_id)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == to_point_id:
            break
        if d > dist.get(u, math.inf):
            continue
        for v, w, span_id in adj[u]:
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = (u, span_id)
                heapq.heappush(heap, (nd, v))

    if to_point_id not in dist:
        return None  # no cable path between them

    # Walk prev back to the source, then flip to source→target order.
    ordered_ids, span_ids = [to_point_id], []
    cur = to_point_id
    while cur in prev:
        parent, span_id = prev[cur]
        span_ids.append(span_id)
        ordered_ids.append(parent)
        cur = parent
    ordered_ids.reverse()
    span_ids.reverse()

    span_by_id = {
        s.id: s for s in FibreSpan.objects.filter(operator_id=operator_id, id__in=span_ids)
    }
    return {
        "points": [points[pid] for pid in ordered_ids],
        "spans": [span_by_id[sid] for sid in span_ids if sid in span_by_id],
        "total_m": round(dist[to_point_id], 1),
        "span_count": len(span_ids),
        # Splices happen at each intermediate point (not the two endpoints).
        "splice_count": max(len(ordered_ids) - 2, 0),
    }


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
