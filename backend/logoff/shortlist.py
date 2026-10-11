"""Pick up to 8 candidates that fit the time budget and the mood."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .geo import bearing_deg, compass, haversine_m
from .models import Candidate, Place, Prefs
from .timing import walk_minutes

MAX_CANDIDATES = 8
WALK_SHARE = 0.6  # round trip may use at most 60% of the time
LANDMARK_KINDS = {"place_of_worship", "attraction", "viewpoint"}
LARGE_PARK_M2 = 20_000

KIND_WEIGHT = {
    "calm": {"park": 3, "garden": 3, "water": 3, "nature_reserve": 3, "place_of_worship": 2.5,
             "wood": 2, "viewpoint": 2, "attraction": 1, "peak": 1},
    "curious": {"viewpoint": 3, "attraction": 3, "peak": 2.5, "nature_reserve": 2.5, "water": 2,
                "place_of_worship": 2, "garden": 1.5, "wood": 1.5, "park": 1},
    "restless": {"nature_reserve": 3, "peak": 3, "park": 2.5, "wood": 2.5, "viewpoint": 2,
                 "water": 2, "garden": 1, "attraction": 1, "place_of_worship": 0.5},
    "social": {"park": 3, "attraction": 3, "garden": 2, "viewpoint": 2, "water": 1.5,
               "nature_reserve": 1.5, "place_of_worship": 1, "peak": 1, "wood": 1},
}


def max_walk_min(minutes: int) -> float:
    return WALK_SHARE * minutes / 2


def fits(walk_min: int, minutes: int) -> bool:
    return 2 * walk_min <= WALK_SHARE * minutes


def is_landmark(p: Place) -> bool:
    if not p.named:
        return False
    return p.kind in LANDMARK_KINDS or (p.kind == "park" and p.area_m2 >= LARGE_PARK_M2)


def measure(p: Place, lat: float, lon: float) -> Candidate:
    d = haversine_m(lat, lon, p.lat, p.lon)
    b = bearing_deg(lat, lon, p.lat, p.lon)
    long_name, short = compass(b)
    return Candidate(
        id="",
        place=p,
        distance_m=round(d),
        walk_min=walk_minutes(d),
        bearing_deg=round(b, 1),
        direction=long_name,
        direction_short=short,
    )


def score(c: Candidate, prefs: Prefs, rain_risk: bool) -> float:
    p = c.place
    s = float(KIND_WEIGHT[prefs.mood].get(p.kind, 1))
    f = min(1.0, c.walk_min / max(1.0, max_walk_min(prefs.minutes)))  # 0 near .. 1 at limit
    if prefs.mood == "restless" or prefs.energy == "high":
        s += 1.5 * f
    if prefs.energy == "low" or prefs.mood == "calm":
        s += 1.0 * (1 - f)
    if prefs.mood == "social" or prefs.company == "others":
        s += 1.5 * min(1.0, math.log10(p.area_m2 + 1) / 5)
    if p.named:
        s += 0.5
    if rain_risk:
        s += 3.0 * (1 - f)
    return s


def shortlist(
    places: Iterable[Place],
    lat: float,
    lon: float,
    prefs: Prefs,
    *,
    after_dark: bool = False,
    rain_risk: bool = False,
    exclude: Iterable[str] = (),
    limit: int = MAX_CANDIDATES,
) -> list[Candidate]:
    skip = set(exclude)
    pool = []
    for p in places:
        if p.osm_id in skip:
            continue
        if after_dark and not is_landmark(p):
            continue
        c = measure(p, lat, lon)
        if fits(c.walk_min, prefs.minutes):
            pool.append((score(c, prefs, rain_risk), c))

    # Greedy pick with a penalty for repeating a kind, so the list isn't eight parks.
    repeat_penalty = 1.5 if prefs.mood == "curious" else 0.75
    chosen: list[Candidate] = []
    kinds: dict[str, int] = {}
    pool.sort(key=lambda sc: (-sc[0], sc[1].distance_m, sc[1].place.osm_id))
    while pool and len(chosen) < limit:
        best_i = max(
            range(len(pool)),
            key=lambda i: (pool[i][0] - repeat_penalty * kinds.get(pool[i][1].place.kind, 0),
                           -pool[i][1].distance_m),
        )
        _, c = pool.pop(best_i)
        kinds[c.place.kind] = kinds.get(c.place.kind, 0) + 1
        chosen.append(c)

    if rain_risk:
        chosen.sort(key=lambda c: (c.walk_min, c.distance_m))
    return [c.model_copy(update={"id": f"P{i}"}) for i, c in enumerate(chosen, start=1)]
