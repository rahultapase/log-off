"""Walking minutes and the leave-by / back-by window. Deterministic; Gemma never does this."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .models import Company, TimeWindow, Weather

DETOUR = 1.3  # straight line -> street distance
WALK_M_PER_MIN = 75  # ~4.5 km/h
DAYLIGHT_MARGIN = timedelta(minutes=5)
RAIN_RISK_PCT = 60


def walk_minutes(distance_m: float) -> int:
    return max(1, math.ceil(distance_m * DETOUR / WALK_M_PER_MIN))


def round_up_5(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0) + (timedelta(minutes=1) if dt.second or dt.microsecond else timedelta(0))
    extra = (-dt.minute) % 5
    return dt + timedelta(minutes=extra)


def fmt_time(dt: datetime) -> str:
    """'5:05 PM' (no leading zero, works on Windows)."""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def max_precip(weather: Weather, start: datetime, end: datetime) -> int | None:
    """Highest hourly rain chance for any hour overlapping [start, end]."""
    vals = [p for t, p in weather.hourly_precip if t + timedelta(hours=1) > start and t <= end]
    return max(vals) if vals else None


def plan_window(now: datetime, outing_min: int, weather: Weather | None, company: Company) -> TimeWindow:
    """Decide when to go for an outing of outing_min minutes.

    now: before latest_leave (sunset - outing - 5 min) and after sunrise -> go now.
    Too late or too early: solo -> next sunrise; with others -> go anyway (after_dark),
    and the shortlist keeps to named landmark places.
    """
    outing = timedelta(minutes=outing_min)
    leave = round_up_5(now)
    if weather is None:
        return TimeWindow(
            mode="now",
            leave_by=leave,
            back_by=leave + outing,
            latest_leave=None,
            sunset=None,
            rain_max_pct=None,
            rain_risk=False,
            note="No weather data right now, so there is no daylight or rain check.",
        )

    sunrise, sunset = weather.sunrise_today, weather.sunset_today
    latest = sunset - outing - DAYLIGHT_MARGIN
    notes: list[str] = []

    if sunrise <= leave <= latest:
        mode = "now"
        notes.append(f"Daylight until {fmt_time(sunset)}.")
    elif company == "others":
        mode = "after_dark"
        notes.append("It will be dark, so this sticks to named, busy places. Stay together.")
    else:
        mode = "later"
        if leave < sunrise:
            next_rise, sunset = sunrise, weather.sunset_today
        else:
            next_rise, sunset = weather.sunrise_tomorrow, weather.sunset_tomorrow
        leave = round_up_5(next_rise)
        latest = sunset - outing - DAYLIGHT_MARGIN
        day = "this morning" if next_rise.date() == now.date() else "tomorrow morning"
        notes.append(f"It's dark until sunrise ({fmt_time(next_rise)}). Go {day} instead.")

    back = leave + outing
    rain = max_precip(weather, leave, back)
    rain_risk = rain is not None and rain >= RAIN_RISK_PCT
    if rain_risk:
        notes.append(f"{rain}% chance of rain, so this is the nearest good place.")

    return TimeWindow(
        mode=mode,
        leave_by=leave,
        back_by=back,
        latest_leave=latest if mode != "after_dark" else None,
        sunset=sunset,
        rain_max_pct=rain,
        rain_risk=rain_risk,
        note=" ".join(notes),
    )


def with_outing(window: TimeWindow, outing_min: int) -> TimeWindow:
    """Same decision, back-by worked out from the actual outing (2*walk + activity)."""
    return window.model_copy(update={"back_by": window.leave_by + timedelta(minutes=outing_min)})
