"""Nominatim search and reverse lookup. Coordinates are rounded to 3 dp before any call."""

from __future__ import annotations

import httpx

from . import cache
from .geo import round_coord
from .models import Area

NOMINATIM = "https://nominatim.openstreetmap.org"
CACHE_S = 7 * 24 * 3600


class GeocodeError(Exception):
    pass


def _label(address: dict, fallback: str) -> str:
    parts: list[str] = []
    for key in ("neighbourhood", "suburb", "village", "town", "city_district", "city", "county"):
        val = address.get(key)
        if val and val not in parts:
            parts.append(val)
        if len(parts) == 2:
            break
    return ", ".join(parts) if parts else fallback


async def search(client: httpx.AsyncClient, query: str) -> Area:
    query = " ".join(query.split())[:120]
    if not query:
        raise GeocodeError("Type an area, like a neighbourhood and city.")
    key = f"geocode_{query.lower()}"
    hit = cache.get(key, CACHE_S)
    if hit:
        return Area(**hit)
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    try:
        r = await client.get(f"{NOMINATIM}/search", params=params, timeout=15)
        r.raise_for_status()
        rows = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodeError("The place search (Nominatim) did not answer. Try again in a minute.") from exc
    if not rows:
        raise GeocodeError(f'Couldn\'t find "{query}". Try a bigger area name.')
    row = rows[0]
    area = Area(
        lat=round_coord(float(row["lat"])),
        lon=round_coord(float(row["lon"])),
        label=_label(row.get("address", {}), row.get("name") or query),
    )
    cache.put(key, area.model_dump())
    return area


async def reverse(client: httpx.AsyncClient, lat: float, lon: float) -> Area:
    lat, lon = round_coord(lat), round_coord(lon)
    key = f"reverse_{lat:.3f}_{lon:.3f}"
    hit = cache.get(key, CACHE_S)
    if hit:
        return Area(**hit)
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 15, "addressdetails": 1}
    label = "Your area"
    try:
        r = await client.get(f"{NOMINATIM}/reverse", params=params, timeout=15)
        r.raise_for_status()
        label = _label(r.json().get("address", {}), label)
    except (httpx.HTTPError, ValueError):
        return Area(lat=lat, lon=lon, label=label)  # label is optional; don't cache a miss
    area = Area(lat=lat, lon=lon, label=label)
    cache.put(key, area.model_dump())
    return area
