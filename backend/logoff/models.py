"""Data shapes shared across the backend."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Mood = Literal["calm", "curious", "restless", "social"]
Energy = Literal["low", "medium", "high"]
Company = Literal["solo", "others"]
Minutes = Literal[15, 30, 45, 60]

# OSM feature kinds we look for.
Kind = Literal[
    "park",
    "garden",
    "nature_reserve",
    "viewpoint",
    "attraction",
    "water",
    "peak",
    "wood",
    "place_of_worship",
]


class Prefs(BaseModel):
    mood: Mood
    minutes: Minutes
    energy: Energy
    company: Company


class Area(BaseModel):
    """A rounded location. Coordinates never leave the backend except to map/weather APIs."""

    lat: float
    lon: float
    label: str


class Place(BaseModel):
    osm_id: str  # e.g. "way/152185039"
    name: str | None
    kind: Kind
    lat: float
    lon: float
    label: str  # name, or "Unnamed park off <street>"
    named: bool
    area_m2: float = 0.0


class Candidate(BaseModel):
    """A place with distances worked out from the user's area."""

    id: str  # P1..P8, assigned by the shortlist
    place: Place
    distance_m: float
    walk_min: int
    bearing_deg: float
    direction: str  # "north-east"
    direction_short: str  # "NE"


class Weather(BaseModel):
    temp_c: float
    feels_c: float
    code: int
    description: str
    is_day: bool
    sunrise_today: datetime
    sunset_today: datetime
    sunrise_tomorrow: datetime
    sunset_tomorrow: datetime
    hourly_precip: list[tuple[datetime, int]] = Field(default_factory=list)


class TimeWindow(BaseModel):
    mode: Literal["now", "after_dark", "later"]
    leave_by: datetime
    back_by: datetime
    latest_leave: datetime | None  # latest departure that still gets you back in daylight
    sunset: datetime | None
    rain_max_pct: int | None
    rain_risk: bool
    note: str


class GemmaPick(BaseModel):
    """What Gemma must return. Steps refer to the place as {place}."""

    place_id: str
    title: str = Field(min_length=3, max_length=80)
    steps: list[str] = Field(min_length=2, max_length=4)
    duration_min: int = Field(ge=5, le=60)
    why: str = Field(min_length=3, max_length=240)
