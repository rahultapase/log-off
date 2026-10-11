"""Facts -> Gemma -> validator -> one retry -> fallback. Shared by the API and the eval script."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import httpx

from . import fallback, gemma, places, validate, weather
from .cache import DATA_DIR
from .models import Area, Candidate, Place, Prefs, TimeWindow
from .shortlist import max_walk_min, shortlist
from .timing import fmt_time, plan_window, with_outing

RUNS_LOG = DATA_DIR / "runs.jsonl"

KIND_WORDS = {
    "park": "park", "garden": "garden", "nature_reserve": "nature reserve", "viewpoint": "viewpoint",
    "attraction": "local attraction", "water": "lake or pond", "peak": "hilltop", "wood": "wood",
    "place_of_worship": "temple or shrine",
}
MOOD_FIT = {
    "calm": "quiet enough to slow down",
    "curious": "something different to look at",
    "restless": "far enough to stretch your legs",
    "social": "room for a group",
}


class PlanError(Exception):
    """A human sentence for the UI."""


def _log(entry: dict[str, Any]) -> None:
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def why_facts(c: Candidate, prefs: Prefs, window: TimeWindow | None, picked_by: str) -> list[str]:
    """'Why this place', from code, not from the model."""
    facts = [
        f"{c.walk_min} min walk {c.direction}, so the round trip is {2 * c.walk_min} of your {prefs.minutes} min.",
        f"A {KIND_WORDS.get(c.place.kind, c.place.kind)}: {MOOD_FIT[prefs.mood]}.",
    ]
    if not c.place.named:
        facts.append("It has no name on OpenStreetMap, so it's labelled by the nearest street.")
    if window is not None and window.rain_risk:
        facts.append(f"{window.rain_max_pct}% chance of rain, so it's the nearest good option.")
    if window is not None and window.mode == "after_dark":
        facts.append("It's a named landmark, a safer choice after dark.")
    facts.append(f"Picked by {picked_by} from {{n}} that fit your time.")
    return facts


async def make_ticket(
    client: httpx.AsyncClient,
    area: Area,
    prefs: Prefs,
    *,
    now: datetime | None = None,
    exclude: list[str] | tuple[str, ...] = (),
    tag: str = "app",
) -> dict[str, Any]:
    try:
        place_res = await places.fetch(client, area.lat, area.lon)
    except places.PlacesError as exc:
        raise PlanError(str(exc)) from exc
    all_places = [Place(**p) for p in place_res["places"]]

    weather_note = None
    try:
        wx = await weather.fetch(client, area.lat, area.lon)
        weather_line = weather.summary(wx)
        tz = wx.sunset_today.tzinfo
    except weather.WeatherError as exc:
        wx, weather_line, tz = None, "Weather unavailable", None
        weather_note = f"{exc} The ticket works without it, but there's no leave-by daylight check."
    now = now or (datetime.now(tz) if tz else datetime.now().astimezone())

    window = plan_window(now, prefs.minutes, wx, prefs.company)
    cands = shortlist(
        all_places, area.lat, area.lon, prefs,
        after_dark=window.mode == "after_dark", rain_risk=window.rain_risk, exclude=exclude,
    )
    if not cands:
        if exclude:
            raise PlanError("That's every mapped place that fits your time. Start over to see them again.")
        reach = int(max_walk_min(prefs.minutes))
        raise PlanError(
            f"Nothing on the map is within a {reach} minute walk, which is what {prefs.minutes} minutes allows. "
            "Try a longer time."
        )

    msgs = gemma.messages(prefs, weather_line, window, cands)
    attempts: list[dict[str, Any]] = []
    picked = None
    ollama_error = None
    for attempt in (1, 2):
        try:
            raw, latency = await gemma.chat(client, msgs)
        except gemma.GemmaError as exc:
            ollama_error = str(exc)
            break
        verdict = validate.check(raw, cands, prefs, window)
        rec = {
            "attempt": attempt, "valid": verdict.ok, "rule": verdict.rule, "reason": verdict.reason,
            "invented": verdict.invented, "latency_s": round(latency, 2), "raw": raw,
        }
        attempts.append(rec)
        _log({"ts": time.time(), "tag": tag, "model": gemma.MODEL, "prefs": prefs.model_dump(),
              "mode": window.mode, **rec})
        if verdict.ok:
            picked = verdict.pick
            break
        msgs = gemma.retry_messages(msgs, raw, verdict.reason or "invalid")

    if picked is not None:
        source = "gemma"
        chosen = next(c for c in cands if c.id == picked.place_id.strip())
    else:
        source = "fallback"
        chosen = cands[0]
        picked = fallback.activity(chosen, prefs)
        if ollama_error:
            _log({"ts": time.time(), "tag": tag, "model": gemma.MODEL, "prefs": prefs.model_dump(),
                  "attempt": 0, "valid": False, "reason": ollama_error})

    rendered = validate.render(picked, chosen.place.label)
    final = with_outing(window, 2 * chosen.walk_min + picked.duration_min)
    picked_by = f"{gemma.display_name()} on this computer" if source == "gemma" else "a built-in template"
    n_text = "the only mapped place" if len(cands) == 1 else f"{len(cands)} real places"
    facts = [f.replace("{n}", n_text) for f in why_facts(chosen, prefs, window, picked_by)]

    notes = [n for n in (final.note, weather_note) if n]
    if ollama_error:
        notes.append("Gemma isn't running (start Ollama), so this activity is a built-in one.")

    return {
        "area_label": area.label,
        "place": {
            "osm_id": chosen.place.osm_id,
            "label": chosen.place.label,
            "kind": chosen.place.kind,
            "kind_word": KIND_WORDS.get(chosen.place.kind, chosen.place.kind),
            "named": chosen.place.named,
            "walk_min": chosen.walk_min,
            "direction": chosen.direction,
            "direction_short": chosen.direction_short,
            "bearing_deg": chosen.bearing_deg,
        },
        "mode": final.mode,
        "now": now.isoformat(),
        "leave_by": final.leave_by.isoformat(),
        "back_by": final.back_by.isoformat(),
        "leave_by_text": fmt_time(final.leave_by),
        "back_by_text": fmt_time(final.back_by),
        "latest_leave_text": fmt_time(final.latest_leave) if final.latest_leave else None,
        "sunset_text": fmt_time(final.sunset) if final.sunset else None,
        "weather": weather_line,
        "rain_pct": final.rain_max_pct,
        "notes": notes,
        "title": rendered.title,
        "steps": rendered.steps,
        "duration_min": rendered.duration_min,
        "gemma_why": rendered.why if source == "gemma" else None,
        "why": facts,
        "source": source,
        "model": gemma.display_name() if source == "gemma" else None,
        "attempts": [{k: v for k, v in a.items() if k != "raw"} for a in attempts],
        "candidates": len(cands),
        "places_source": place_res["source"],
    }
