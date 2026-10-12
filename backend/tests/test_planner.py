"""End-to-end planner paths with places, weather and Gemma stubbed: Ollama off, weather off,
retry, invented place caught."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from logoff import planner
from logoff.models import Area, Place, Prefs, Weather

TZ = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=TZ)
AREA = Area(lat=0.0, lon=0.0, label="Test Area")
PREFS = Prefs(mood="calm", minutes=30, energy="low", company="solo")
PLACES = [
    Place(osm_id="way/1", name="Near Park", kind="park", lat=0.002, lon=0, label="Near Park", named=True, area_m2=5000),
    Place(osm_id="way/2", name="Mid Garden", kind="garden", lat=0.004, lon=0, label="Mid Garden", named=True, area_m2=3000),
]
WX = Weather(temp_c=28, feels_c=31, code=1, description="mostly clear", is_day=True,
             sunrise_today=NOW.replace(hour=6, minute=30), sunset_today=NOW.replace(hour=18, minute=15),
             sunrise_tomorrow=NOW.replace(hour=6, minute=31) + timedelta(days=1),
             sunset_tomorrow=NOW.replace(hour=18, minute=14) + timedelta(days=1), hourly_precip=[])


def good(pid="P1", **over):
    d = {"place_id": pid, "title": "Five sounds", "steps": ["Walk to {place}.", "Count five sounds."],
         "duration_min": 10, "why": "Quiet enough."}
    d.update(over)
    return json.dumps(d)


@pytest.fixture(autouse=True)
def stubs(monkeypatch, tmp_path):
    monkeypatch.setattr(planner, "RUNS_LOG", tmp_path / "runs.jsonl")

    async def fake_places(_, lat, lon):
        return {"source": "test", "places": [p.model_dump() for p in PLACES], "streets": 0, "notes": []}

    async def fake_weather(_, lat, lon):
        return WX

    monkeypatch.setattr(planner.places, "fetch", fake_places)
    monkeypatch.setattr(planner.weather, "fetch", fake_weather)


def run(**kw):
    return asyncio.run(planner.make_ticket(None, AREA, PREFS, now=NOW, **kw))


def gemma_returns(monkeypatch, *answers):
    calls = iter(answers)

    async def fake_chat(_, msgs):
        a = next(calls)
        if isinstance(a, Exception):
            raise a
        return a, 0.1

    monkeypatch.setattr(planner.gemma, "chat", fake_chat)


def test_gemma_first_try(monkeypatch):
    gemma_returns(monkeypatch, good("P2"))
    t = run()
    assert t["source"] == "gemma" and t["place"]["label"] == "Mid Garden"
    assert t["steps"][0] == "Walk to Mid Garden."
    assert t["leave_by_text"] == "4:00 PM" and t["back_by_text"] == "4:26 PM"  # 8 + 8 + 10


def test_invented_place_is_retried_then_fixed(monkeypatch):
    gemma_returns(monkeypatch, good(steps=["Walk to Shiv Temple.", "Sit."]), good())
    t = run()
    assert t["source"] == "gemma"
    assert [a["valid"] for a in t["attempts"]] == [False, True]
    assert t["attempts"][0]["rule"] == 3 and t["attempts"][0]["invented"] == ["Shiv Temple"]


def test_two_bad_answers_fall_back(monkeypatch):
    gemma_returns(monkeypatch, "{oops", good(pid="P7"))
    t = run()
    assert t["source"] == "fallback" and t["model"] is None
    assert t["place"]["label"] == "Near Park"
    assert "{place}" not in " ".join(t["steps"])


def test_ollama_off_falls_back_with_a_note(monkeypatch):
    gemma_returns(monkeypatch, planner.gemma.GemmaError("connection refused"))
    t = run()
    assert t["source"] == "fallback"
    assert any("Gemma isn't running" in n for n in t["notes"])


def test_weather_off_still_gives_a_ticket(monkeypatch):
    async def no_weather(_, lat, lon):
        raise planner.weather.WeatherError("Weather (Open-Meteo) did not answer.")

    monkeypatch.setattr(planner.weather, "fetch", no_weather)
    gemma_returns(monkeypatch, good())
    t = run()
    assert t["source"] == "gemma"
    assert t["sunset_text"] is None and t["weather"] == "Weather unavailable"
    assert any("no leave-by daylight check" in n for n in t["notes"])


def test_exclude_everything_is_a_clear_error(monkeypatch):
    gemma_returns(monkeypatch, good())
    with pytest.raises(planner.PlanError, match="every mapped place"):
        run(exclude=["way/1", "way/2"])
