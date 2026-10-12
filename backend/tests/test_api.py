"""API shape and error handling, with the network and Gemma stubbed out."""

import pytest
from fastapi.testclient import TestClient

from logoff import main
from logoff.models import Area
from logoff.planner import PlanError


@pytest.fixture
def client(monkeypatch):
    with TestClient(main.app) as c:
        yield c


def test_health_reports_ollama_down(client, monkeypatch):
    async def down(_):
        return {"ollama": False, "model": "gemma4:e2b", "model_present": False}

    monkeypatch.setattr(main.gemma, "health", down)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "Ollama isn't running" in body["message"]


def test_locate_needs_exactly_one_input(client):
    assert client.post("/api/locate", json={}).status_code == 422
    assert client.post("/api/locate", json={"query": "x", "lat": 1, "lon": 2}).status_code == 422


def test_locate_rounds_and_labels(client, monkeypatch):
    seen = {}

    async def fake_reverse(_, lat, lon):
        seen["args"] = (lat, lon)
        return Area(lat=round(lat, 3), lon=round(lon, 3), label="Test Area")

    monkeypatch.setattr(main.geocode, "reverse", fake_reverse)
    r = client.post("/api/locate", json={"lat": 10.123456, "lon": 20.987654})
    assert r.status_code == 200
    assert r.json() == {"lat": 10.123, "lon": 20.988, "label": "Test Area"}


def test_locate_not_found_is_a_sentence(client, monkeypatch):
    async def nope(_, q):
        raise main.geocode.GeocodeError(f'Couldn\'t find "{q}". Try a bigger area name.')

    monkeypatch.setattr(main.geocode, "search", nope)
    r = client.post("/api/locate", json={"query": "zzz"})
    assert r.status_code == 404 and "Couldn't find" in r.json()["detail"]


def test_plan_rounds_coords_and_maps_plan_error(client, monkeypatch):
    seen = {}

    async def fake_ticket(_, area, prefs, *, now=None, exclude=(), tag="app"):
        seen["area"] = area
        raise PlanError("Map data (OpenStreetMap) is unavailable right now.")

    monkeypatch.setattr(main, "make_ticket", fake_ticket)
    body = {"lat": 10.123456, "lon": 20.987654, "label": "T",
            "prefs": {"mood": "calm", "minutes": 30, "energy": "low", "company": "solo"}}
    r = client.post("/api/plan", json=body)
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]
    assert (seen["area"].lat, seen["area"].lon) == (10.123, 20.988)


def test_plan_rejects_bad_prefs_and_bad_at(client):
    bad = {"lat": 1, "lon": 2, "prefs": {"mood": "angry", "minutes": 30, "energy": "low", "company": "solo"}}
    assert client.post("/api/plan", json=bad).status_code == 422
    ok = {"lat": 1, "lon": 2, "prefs": {"mood": "calm", "minutes": 30, "energy": "low", "company": "solo"}}
    r = client.post("/api/plan?at=25:99", json=ok)
    assert r.status_code == 422 and "19:30" in r.json()["detail"]


def test_prepare_reports_errors_as_fields(client, monkeypatch):
    async def no_places(_, lat, lon):
        raise main.places.PlacesError("Map data (OpenStreetMap) is unavailable right now.")

    async def no_weather(_, lat, lon):
        raise main.weather.WeatherError("Weather (Open-Meteo) did not answer.")

    monkeypatch.setattr(main.places, "fetch", no_places)
    monkeypatch.setattr(main.weather, "fetch", no_weather)
    r = client.post("/api/prepare", json={"lat": 1.0, "lon": 2.0})
    assert r.status_code == 200
    body = r.json()
    assert body["places"] is None and "unavailable" in body["places_error"]
    assert body["sunset_text"] is None and "Open-Meteo" in body["weather_error"]


def test_prepare_returns_sun_times_and_mock_now(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=5, minutes=30))
    day = datetime(2026, 10, 12, tzinfo=tz)
    wx = main.weather.Weather(
        temp_c=26, feels_c=29, code=0, description="clear sky", is_day=True,
        sunrise_today=day.replace(hour=6, minute=31), sunset_today=day.replace(hour=18, minute=17),
        sunrise_tomorrow=day.replace(hour=6, minute=31) + timedelta(days=1),
        sunset_tomorrow=day.replace(hour=18, minute=16) + timedelta(days=1),
    )

    async def fake_weather(_, lat, lon):
        return wx

    async def fake_places(_, lat, lon):
        return {"source": "test", "places": [{"named": True}, {"named": False}], "streets": 0, "notes": []}

    monkeypatch.setattr(main.weather, "fetch", fake_weather)
    monkeypatch.setattr(main.places, "fetch", fake_places)
    r = client.post("/api/prepare?at=16:30", json={"lat": 1.0, "lon": 2.0})
    body = r.json()
    assert r.status_code == 200
    assert body["places"] == 2 and body["named"] == 1
    assert body["sunset_text"] == "6:17 PM" and body["sunrise_tomorrow_text"] == "6:31 AM"
    assert body["now"].startswith(datetime.now(tz).strftime("%Y-%m-%d")) and "T16:30:00" in body["now"]


def test_unknown_api_route_is_404(client):
    assert client.get("/api/nope").status_code == 404
