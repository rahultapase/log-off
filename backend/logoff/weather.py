"""Open-Meteo forecast: current conditions, hourly rain chance, sunrise and sunset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from . import cache
from .models import Weather

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
CACHE_S = 15 * 60

# WMO weather interpretation codes (Open-Meteo docs), shortened.
WMO = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}

# Codes where an exposed outdoor activity is a bad idea.
SEVERE_CODES = {65, 67, 75, 82, 86, 95, 96, 99}


class WeatherError(Exception):
    pass


def parse(payload: dict) -> Weather:
    """Turn an Open-Meteo response into a Weather. Local times get the response's UTC offset."""
    tz = timezone(timedelta(seconds=int(payload.get("utc_offset_seconds", 0))))

    def t(s: str) -> datetime:
        return datetime.fromisoformat(s).replace(tzinfo=tz)

    cur = payload["current"]
    daily = payload["daily"]
    hourly = payload.get("hourly", {})
    code = int(cur["weather_code"])
    precip = [
        (t(ts), int(p if p is not None else 0))
        for ts, p in zip(hourly.get("time", []), hourly.get("precipitation_probability", []))
    ]
    return Weather(
        temp_c=float(cur["temperature_2m"]),
        feels_c=float(cur["apparent_temperature"]),
        code=code,
        description=WMO.get(code, "unsettled"),
        is_day=bool(cur["is_day"]),
        sunrise_today=t(daily["sunrise"][0]),
        sunset_today=t(daily["sunset"][0]),
        sunrise_tomorrow=t(daily["sunrise"][1]),
        sunset_tomorrow=t(daily["sunset"][1]),
        hourly_precip=precip,
    )


async def fetch(client: httpx.AsyncClient, lat: float, lon: float) -> Weather:
    key = f"weather_{lat:.3f}_{lon:.3f}"
    hit = cache.get(key, CACHE_S)
    if hit is None:
        params = {
            "latitude": f"{lat:.3f}",
            "longitude": f"{lon:.3f}",
            "current": "temperature_2m,apparent_temperature,weather_code,is_day",
            "hourly": "precipitation_probability",
            "daily": "sunrise,sunset",
            "timezone": "auto",
            "forecast_days": 2,
        }
        try:
            r = await client.get(OPEN_METEO, params=params, timeout=15)
            r.raise_for_status()
            hit = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeatherError("Weather (Open-Meteo) did not answer.") from exc
        cache.put(key, hit)
    try:
        return parse(hit)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("Weather data came back in a shape I don't understand.") from exc


def summary(w: Weather) -> str:
    """One short line for the ticket and the prompt."""
    feels = f", feels like {round(w.feels_c)}\u00b0C" if abs(w.feels_c - w.temp_c) >= 2 else ""
    return f"{w.description.capitalize()}, {round(w.temp_c)}\u00b0C{feels}"
