"""Distance, bearing and labelling helpers. Pure functions, no I/O."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8

_COMPASS = [
    ("north", "N"),
    ("north-east", "NE"),
    ("east", "E"),
    ("south-east", "SE"),
    ("south", "S"),
    ("south-west", "SW"),
    ("west", "W"),
    ("north-west", "NW"),
]


def round_coord(value: float, dp: int = 3) -> float:
    """Round a coordinate (3 dp is roughly 100 m) before it leaves the machine."""
    return round(value, dp)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, 0 = north, clockwise, in [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(deg: float) -> tuple[str, str]:
    """8-point compass label for a bearing: ("north-east", "NE")."""
    idx = int(((deg % 360) + 22.5) // 45) % 8
    return _COMPASS[idx]


def polygon_area_m2(points: Sequence[tuple[float, float]]) -> float:
    """Approximate area of a closed (lat, lon) ring using a local flat projection."""
    if len(points) < 3:
        return 0.0
    lat0 = math.radians(sum(p[0] for p in points) / len(points))
    k = math.pi / 180 * EARTH_RADIUS_M
    xy = [(p[1] * k * math.cos(lat0), p[0] * k) for p in points]
    total = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def bbox_area_m2(minlat: float, minlon: float, maxlat: float, maxlon: float) -> float:
    """Area of a lat/lon bounding box; a rough upper bound for a feature's size."""
    h = haversine_m(minlat, minlon, maxlat, minlon)
    w = haversine_m(minlat, minlon, minlat, maxlon)
    return h * w


def nearest_street(
    lat: float,
    lon: float,
    streets: Iterable[tuple[str, Sequence[tuple[float, float]]]],
    max_m: float = 300,
) -> str | None:
    """Name of the closest named street (by nearest vertex) within max_m, else None."""
    best_name, best_d = None, max_m
    for name, pts in streets:
        for plat, plon in pts:
            d = haversine_m(lat, lon, plat, plon)
            if d < best_d:
                best_name, best_d = name, d
    return best_name
