"""Real places near the user, from OpenStreetMap.

Overpass first (one small query per category, two mirrors). If a key category fails,
the OSM main API bbox call is merged in and tags are filtered locally. Results are cached
for 24 h per rounded area, and a stale cache beats an error.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from . import cache
from .geo import bbox_area_m2, haversine_m, nearest_street, polygon_area_m2
from .models import Place

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OSM_MAP_API = "https://api.openstreetmap.org/api/0.6/map.json"
RADIUS_M = 2000
FALLBACK_HALF_DEG = 0.008  # ~0.016 deg box, checked to answer in ~3 s
CACHE_S = 24 * 3600
OVERPASS_TIMEOUT_S = 20
MIN_UNNAMED_PARK_M2 = 1000
NEAR_DUP_M = 150
OVERPASS_BUDGET_S = 35  # stop trying Overpass after this, use the fallback
OVERPASS_GAP_S = 1.0  # be polite between queries (Overpass has per-IP slots)

# One small query each. {r} radius, {lat}/{lon} centre.
CATEGORY_QUERIES = {
    "leisure": 'nwr["leisure"~"^(park|garden|nature_reserve)$"](around:{r},{lat},{lon});out tags bb;',
    "tourism": 'nwr["tourism"~"^(viewpoint|attraction)$"](around:{r},{lat},{lon});out tags bb;',
    "natural": 'nwr["natural"~"^(water|peak|wood)$"]["name"](around:{r},{lat},{lon});out tags bb;',
    "worship": 'nwr["amenity"="place_of_worship"]["name"](around:{r},{lat},{lon});out tags bb;',
    "streets": 'way["highway"]["name"](around:{r},{lat},{lon});out tags geom qt;',
}
KEY_CATEGORIES = {"leisure", "streets"}


class PlacesError(Exception):
    pass


def classify(tags: dict[str, str]) -> str | None:
    """Map OSM tags to one of our kinds, or None to skip."""
    if tags.get("access") in {"private", "no"}:
        return None
    leisure = tags.get("leisure")
    if leisure in {"park", "garden", "nature_reserve"}:
        return leisure
    tourism = tags.get("tourism")
    if tourism in {"viewpoint", "attraction"}:
        return tourism
    natural = tags.get("natural")
    if natural in {"water", "peak", "wood"}:
        return natural
    if tags.get("amenity") == "place_of_worship":
        return "place_of_worship"
    return None


def display_name(tags: dict[str, str]) -> str | None:
    name = (tags.get("name:en") or tags.get("name") or "").strip()
    return name or None


def make_place(
    osm_id: str,
    tags: dict[str, str],
    lat: float,
    lon: float,
    area_m2: float,
    streets: list[tuple[str, list[tuple[float, float]]]],
) -> Place | None:
    kind = classify(tags)
    if kind is None:
        return None
    name = display_name(tags)
    if name is None:
        # Only unnamed parks with real size are worth suggesting; unnamed gardens,
        # water and woods are often private or not walkable.
        if kind != "park" or area_m2 < MIN_UNNAMED_PARK_M2:
            return None
        street = nearest_street(lat, lon, streets)
        label = f"Unnamed park off {street}" if street else "Unnamed park"
    else:
        label = name
    return Place(
        osm_id=osm_id,
        name=name,
        kind=kind,  # type: ignore[arg-type]
        lat=lat,
        lon=lon,
        label=label,
        named=name is not None,
        area_m2=round(area_m2, 1),
    )


def _overpass_elements_to_raw(elements: list[dict]) -> list[dict]:
    """Overpass `out tags bb` -> raw dicts with a centre and a size."""
    raw = []
    for el in elements:
        tags = el.get("tags") or {}
        if "lat" in el and "lon" in el:
            lat, lon, area = el["lat"], el["lon"], 0.0
        elif "center" in el:
            lat, lon, area = el["center"]["lat"], el["center"]["lon"], 0.0
        elif "bounds" in el:
            b = el["bounds"]
            lat = (b["minlat"] + b["maxlat"]) / 2
            lon = (b["minlon"] + b["maxlon"]) / 2
            area = bbox_area_m2(b["minlat"], b["minlon"], b["maxlat"], b["maxlon"])
        else:
            continue
        raw.append({"osm_id": f"{el['type']}/{el['id']}", "tags": tags, "lat": lat, "lon": lon, "area": area})
    return raw


def _overpass_streets(elements: list[dict]) -> list[tuple[str, list[tuple[float, float]]]]:
    out = []
    for el in elements:
        name = display_name(el.get("tags") or {})
        geom = el.get("geometry") or []
        if name and geom:
            out.append((name, [(g["lat"], g["lon"]) for g in geom]))
    return out


def parse_map_api(payload: dict) -> tuple[list[dict], list[tuple[str, list[tuple[float, float]]]]]:
    """OSM main API map.json -> (raw places, named streets). Way centroid = mean of node coords."""
    nodes: dict[int, tuple[float, float]] = {}
    for el in payload.get("elements", []):
        if el.get("type") == "node" and "lat" in el:
            nodes[el["id"]] = (el["lat"], el["lon"])
    raw: list[dict] = []
    streets: list[tuple[str, list[tuple[float, float]]]] = []
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        if not tags:
            continue
        if el["type"] == "node":
            if classify(tags):
                raw.append({"osm_id": f"node/{el['id']}", "tags": tags, "lat": el["lat"], "lon": el["lon"], "area": 0.0})
        elif el["type"] == "way":
            pts = [nodes[n] for n in el.get("nodes", []) if n in nodes]
            if not pts:
                continue
            if "highway" in tags and display_name(tags):
                streets.append((display_name(tags), pts))  # type: ignore[arg-type]
            if classify(tags):
                ring = pts[:-1] if len(pts) > 3 and pts[0] == pts[-1] else pts
                lat = sum(p[0] for p in ring) / len(ring)
                lon = sum(p[1] for p in ring) / len(ring)
                area = polygon_area_m2(ring) if pts[0] == pts[-1] else 0.0
                raw.append({"osm_id": f"way/{el['id']}", "tags": tags, "lat": lat, "lon": lon, "area": area})
    return raw, streets


def build_places(
    raw: list[dict],
    streets: list[tuple[str, list[tuple[float, float]]]],
    centre: tuple[float, float],
) -> list[Place]:
    """Classify, label, keep within radius, and de-duplicate by OSM id and by name."""
    by_id: dict[str, Place] = {}
    for r in raw:
        if haversine_m(centre[0], centre[1], r["lat"], r["lon"]) > RADIUS_M:
            continue
        p = make_place(r["osm_id"], r["tags"], r["lat"], r["lon"], r["area"], streets)
        if p is not None and p.osm_id not in by_id:
            by_id[p.osm_id] = p
    by_label: dict[str, Place] = {}
    for p in by_id.values():
        key = p.label.lower() if p.named else p.osm_id
        prev = by_label.get(key)
        if prev is None or p.area_m2 > prev.area_m2:
            by_label[key] = p
    # Same kind within NEAR_DUP_M is one real place mapped twice (e.g. "ISCKON" and "ISKON").
    kept: list[Place] = []
    for p in sorted(by_label.values(), key=lambda q: (not q.named, -q.area_m2, q.osm_id)):
        if any(k.kind == p.kind and haversine_m(k.lat, k.lon, p.lat, p.lon) < NEAR_DUP_M for k in kept):
            continue
        kept.append(p)
    return kept


async def _overpass(client: httpx.AsyncClient, query: str) -> tuple[list[dict], str]:
    last: Exception | None = None
    # The main instance answers most of the time when retried; kumi was returning 500s on 12 Oct.
    for attempt, url in enumerate([*OVERPASS_MIRRORS, OVERPASS_MIRRORS[0]]):
        if attempt == len(OVERPASS_MIRRORS):
            await asyncio.sleep(2)
        try:
            r = await client.post(
                url,
                data={"data": f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];{query}"},
                timeout=OVERPASS_TIMEOUT_S + 2,
            )
            r.raise_for_status()
            return r.json().get("elements", []), httpx.URL(url).host
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
    raise PlacesError(f"Overpass failed on all mirrors: {last!r}")


async def _map_api(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    d = FALLBACK_HALF_DEG
    bbox = f"{lon - d:.4f},{lat - d:.4f},{lon + d:.4f},{lat + d:.4f}"
    r = await client.get(OSM_MAP_API, params={"bbox": bbox}, timeout=30)
    r.raise_for_status()
    return r.json()


async def fetch(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    """Return {"source", "places": [Place dict], "streets": int, "fetched_at", "notes"}."""
    key = f"places_{lat:.3f}_{lon:.3f}"
    hit = cache.get(key, CACHE_S)
    if hit:
        return {**hit, "source": f"cache ({hit['source']})"}

    raw: list[dict] = []
    streets: list[tuple[str, list[tuple[float, float]]]] = []
    sources: set[str] = set()
    failed: list[str] = []
    started = time.monotonic()
    for i, (cat, tmpl) in enumerate(CATEGORY_QUERIES.items()):
        if time.monotonic() - started > OVERPASS_BUDGET_S:
            failed.append(cat)
            continue
        if i:
            await asyncio.sleep(OVERPASS_GAP_S)
        try:
            elements, host = await _overpass(client, tmpl.format(r=RADIUS_M, lat=f"{lat:.3f}", lon=f"{lon:.3f}"))
        except PlacesError:
            failed.append(cat)
            if cat == "leisure":
                # Overpass is struggling; don't spend 20 s per query on the rest.
                failed.extend(c for c in CATEGORY_QUERIES if c != "leisure")
                break
            continue
        sources.add(host)
        if cat == "streets":
            streets = _overpass_streets(elements)
        else:
            raw.extend(_overpass_elements_to_raw(elements))

    notes: list[str] = []
    if failed:
        notes.append(f"Overpass failed for: {', '.join(failed)}")
    if KEY_CATEGORIES & set(failed) or len(failed) >= 2:
        try:
            fb_raw, fb_streets = parse_map_api(await _map_api(client, lat, lon))
            raw.extend(fb_raw)
            if not streets:
                streets = fb_streets
            sources.add("api.openstreetmap.org")
            notes.append("merged OSM map API fallback")
        except (httpx.HTTPError, ValueError) as exc:
            notes.append(f"OSM map API failed: {exc!r}")

    places = build_places(raw, streets, (lat, lon))
    if not places:
        stale = cache.get(key, float("inf"))
        if stale:
            return {**stale, "source": f"stale cache ({stale['source']})"}
        raise PlacesError("Map data (OpenStreetMap) is unavailable right now and nothing is cached for this area.")

    result = {
        "source": " + ".join(sorted(sources)),
        "places": [p.model_dump() for p in places],
        "streets": len(streets),
        "fetched_at": time.time(),
        "notes": notes,
    }
    cache.put(key, result)
    return result
