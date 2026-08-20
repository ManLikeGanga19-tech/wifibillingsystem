"""Place/address search for the Map's search box — a thin, provider-agnostic proxy.

Why proxy at all instead of calling a geocoder straight from the browser:
  - No key ever reaches the client. The default (OSM/Photon) needs none, but a deployment can
    swap in a keyed provider via env and the key stays server-side — the no-secrets rule holds.
  - One place to add a courteous User-Agent, a timeout, viewport bias and result normalisation,
    so the frontend gets the same clean shape whatever the upstream is.

Results are biased toward a supplied lat/lon (the current map centre) exactly the way Google/
Apple rank nearby places first — but nothing is HARD-restricted to a country, because every
operator sits somewhere different and the map is multi-tenant. The bias falls out of the
viewport, never a hardcoded Kenya box.
"""

from __future__ import annotations

import httpx
from django.conf import settings


class GeocoderError(Exception):
    """Upstream geocoder was unreachable or misbehaved — surfaced as a 502 to the client."""


def _photon_label(props: dict) -> tuple[str, str]:
    """Split Photon's flat properties into a Google-style (primary, secondary) pair.

    primary   = the thing you typed toward (a place name, or 'street housenumber')
    secondary = the context line beneath it (locality, region, country), deduped and in order.
    """
    name = props.get("name") or ""
    street = props.get("street") or ""
    housenumber = props.get("housenumber") or ""

    if name:
        primary = name
    elif street:
        primary = f"{street} {housenumber}".strip()
    else:
        primary = props.get("city") or props.get("country") or "Unnamed place"

    # Context, nearest-to-broadest, skipping anything already in the primary or repeated.
    context = [
        street if street and street != primary else "",
        props.get("district") or "",
        props.get("city") or props.get("town") or props.get("village") or "",
        props.get("county") or "",
        props.get("state") or "",
        props.get("country") or "",
    ]
    seen: set[str] = {primary}
    ordered: list[str] = []
    for part in context:
        if part and part not in seen:
            seen.add(part)
            ordered.append(part)
    return primary, ", ".join(ordered)


def _search_photon(query: str, lat: float | None, lng: float | None, limit: int) -> list[dict]:
    params: dict[str, object] = {"q": query, "limit": limit, "lang": "en"}
    # Proximity bias — Photon ranks results near this point first (the "results near you" effect).
    if lat is not None and lng is not None:
        params["lat"] = lat
        params["lon"] = lng
    try:
        resp = httpx.get(
            settings.GEOCODER_URL,
            params=params,
            headers={"User-Agent": settings.GEOCODER_USER_AGENT},
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:  # network, timeout, non-2xx, bad JSON
        raise GeocoderError(str(exc)) from exc

    out: list[dict] = []
    for feat in payload.get("features", []):
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(coords) != 2:
            continue  # we only place points, never draw the polygon a place may carry
        props = feat.get("properties") or {}
        primary, secondary = _photon_label(props)
        out.append({
            "label": primary,
            "secondary": secondary,
            "lat": float(coords[1]),
            "lng": float(coords[0]),
            "type": props.get("osm_value") or props.get("type") or "",
        })
    return out


def search(
    query: str, lat: float | None = None, lng: float | None = None, limit: int = 8
) -> list[dict]:
    """Return up to `limit` normalised place suggestions for `query`, biased toward (lat, lng).

    Each result: {label, secondary, lat, lng, type}. Raises GeocoderError on upstream failure.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return []
    limit = max(1, min(limit, 10))
    provider = settings.GEOCODER_PROVIDER
    if provider == "photon":
        return _search_photon(query, lat, lng, limit)
    raise GeocoderError(f"Unknown geocoder provider: {provider!r}")
