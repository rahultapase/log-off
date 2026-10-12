"""FastAPI app. Binds to 127.0.0.1 only; there is no auth because nothing leaves this machine
except rounded coordinates to OpenStreetMap / Open-Meteo.

    uv run uvicorn logoff.main:app --app-dir backend --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import USER_AGENT, __version__, gemma, geocode, places, weather
from .cache import REPO_ROOT
from .geo import round_coord
from .models import Area, Prefs
from .planner import PlanError, make_ticket
from .timing import fmt_time

DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        app.state.http = client
        yield


app = FastAPI(title="Log Off", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)


def problem(status: int, message: str) -> JSONResponse:
    """Errors are one human sentence in `detail`."""
    return JSONResponse(status_code=status, content={"detail": message})


class LocateIn(BaseModel):
    query: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def one_of(self) -> "LocateIn":
        has_q = bool(self.query and self.query.strip())
        has_ll = self.lat is not None and self.lon is not None
        if has_q == has_ll:
            raise ValueError("Send either an area name or your location, not both.")
        return self


class PlanIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field(default="Your area", max_length=120)
    prefs: Prefs
    exclude: list[str] = Field(default_factory=list, max_length=50)


class BadInput(Exception):
    pass


@app.exception_handler(PlanError)
async def plan_error(_: Request, exc: PlanError) -> JSONResponse:
    return problem(503, str(exc))


@app.exception_handler(BadInput)
async def bad_input(_: Request, exc: BadInput) -> JSONResponse:
    return problem(422, str(exc))


@app.get("/api/health")
async def health(request: Request) -> dict:
    h = await gemma.health(request.app.state.http)
    if not h["ollama"]:
        h["message"] = "Ollama isn't running. Start it, and Log Off will use Gemma again."
    elif not h["model_present"]:
        h["message"] = f"Ollama is running but {h['model']} isn't pulled. Run: ollama pull {h['model']}"
    else:
        h["message"] = "Ready."
        # The page calls /api/health on load; start loading Gemma while the user picks options.
        task = asyncio.create_task(gemma.warm(request.app.state.http))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return {"ok": h["ollama"] and h["model_present"], "version": __version__, **h}


_background: set[asyncio.Task] = set()


@app.post("/api/locate")
async def locate(body: LocateIn, request: Request):
    client = request.app.state.http
    try:
        if body.query:
            area = await geocode.search(client, body.query)
        else:
            area = await geocode.reverse(client, body.lat, body.lon)  # type: ignore[arg-type]
    except geocode.GeocodeError as exc:
        return problem(404 if "find" in str(exc) else 503, str(exc))
    return area.model_dump()


_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


async def _mock_now(client: httpx.AsyncClient, lat: float, lon: float, at: str | None) -> datetime | None:
    """`?at=HH:MM` plans as if it were that local time today (for demos and the after-dark path)."""
    if not at:
        return None
    m = _HHMM.match(at)
    if not m:
        raise BadInput("`at` must look like 19:30.")
    try:
        tz = (await weather.fetch(client, lat, lon)).sunset_today.tzinfo
    except weather.WeatherError:
        tz = datetime.now().astimezone().tzinfo
    now = datetime.now(tz)
    return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)


@app.post("/api/plan")
async def plan(body: PlanIn, request: Request, at: str | None = Query(default=None)):
    client = request.app.state.http
    area = Area(lat=round_coord(body.lat), lon=round_coord(body.lon), label=body.label.strip() or "Your area")
    now = await _mock_now(client, area.lat, area.lon, at)
    return await make_ticket(client, area, body.prefs, now=now, exclude=body.exclude)


class PrepareIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@app.post("/api/prepare")
async def prepare(body: PrepareIn, request: Request, at: str | None = Query(default=None)):
    """Fetch (and cache) places + weather for an area so the loading steps and the daylight
    panel report real facts, and /api/plan only has to wait for Gemma."""
    client = request.app.state.http
    lat, lon = round_coord(body.lat), round_coord(body.lon)
    out: dict = {"places": None, "named": None, "places_source": None, "places_error": None,
                 "sunset_text": None, "sunrise_text": None, "weather": None, "weather_error": None,
                 "now": None, "sunrise": None, "sunset": None, "sunrise_tomorrow": None,
                 "sunrise_tomorrow_text": None}
    try:
        res = await places.fetch(client, lat, lon)
        out.update(places=len(res["places"]), named=sum(1 for p in res["places"] if p["named"]),
                   places_source=res["source"])
    except places.PlacesError as exc:
        out["places_error"] = str(exc)
    try:
        wx = await weather.fetch(client, lat, lon)
        now = await _mock_now(client, lat, lon, at) or datetime.now(wx.sunset_today.tzinfo)
        out.update(
            sunset_text=fmt_time(wx.sunset_today), sunrise_text=fmt_time(wx.sunrise_today),
            sunrise_tomorrow_text=fmt_time(wx.sunrise_tomorrow), weather=weather.summary(wx),
            now=now.isoformat(), sunrise=wx.sunrise_today.isoformat(), sunset=wx.sunset_today.isoformat(),
            sunrise_tomorrow=wx.sunrise_tomorrow.isoformat(),
        )
    except weather.WeatherError as exc:
        out["weather_error"] = str(exc)
    return out


@app.get("/api/{rest:path}")
async def api_404(rest: str):
    return problem(404, "No such API route.")


# Built frontend (npm run build). In dev, Vite serves it and proxies /api here.
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        file = (DIST / path).resolve()
        if path and file.is_file() and DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(DIST / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
