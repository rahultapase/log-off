"""Local Gemma 4 through Ollama. Gemma chooses a place from the list and writes the activity;
it never sees coordinates and never computes times or distances."""

from __future__ import annotations

import json
import os
import time

import httpx

from .models import Candidate, GemmaPick, Prefs, TimeWindow

OLLAMA_URL = os.environ.get("LOGOFF_OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("LOGOFF_MODEL", "gemma4:e2b")
TIMEOUT_S = 120

SYSTEM = """You help someone stop scrolling and go outside for a short while.
You get their mood, energy, company, the weather, and a numbered list of real places near them.
Choose ONE place from the list and write a small, specific thing to do there.

Rules:
- place_id must be one of the ids in the list (like "P2").
- Refer to the chosen place only as {place}. Never write any other place, street or landmark name.
- No distances, no clock times, no numbers of metres or kilometres. The app adds those.
- 2 to 4 steps. Each step is one short sentence starting with a verb, under 20 words.
- Make it ONE small task with a clear finish, following the "Task style" line you are given.
  Avoid vague advice like "relax", "enjoy" or "take deep breaths". Don't default to shadows or clouds.
- Something you can do with no equipment, no purchase and no phone.
- duration_min is the time spent AT the place and must not exceed that place's "max minutes there".
- title: under 8 words, names the task. why: one sentence on why this place suits the mood.
- Plain words. No emoji. No dashes as punctuation.

Reply with JSON only."""

# Code decides the shape of the task; Gemma fills in the specifics for the place.
MOOD_STYLE = {
    "calm": "slow and still. Sit or stand in one spot and use your senses: sounds, smells, textures, small living things.",
    "curious": "a small investigation. Look for, compare or work out something specific about this kind of place.",
    "restless": "keep moving most of the time: brisk laps, a loop of the edge, counting steps, a faster stretch, then a cool-down.",
    "social": "something done with or around people: a tiny game, taking turns, a question to ask.",
}
SOCIAL_SOLO = ("being around people without watching anyone closely: sit where people gather, greet one person or "
               "vendor, notice what the place is used for.")
ENERGY_STYLE = {
    "low": "Keep it gentle; sitting is fine.",
    "medium": "A mix of walking and pausing.",
    "high": "Mostly on your feet and moving.",
}


def task_style(prefs: Prefs) -> str:
    style = SOCIAL_SOLO if prefs.mood == "social" and prefs.company == "solo" else MOOD_STYLE[prefs.mood]
    return f"Task style: {style} {ENERGY_STYLE[prefs.energy]}"


def display_name(model: str = MODEL) -> str:
    """'gemma4:e2b' -> 'Gemma 4 E2B'. Anything else is shown as-is."""
    base, _, tag = model.partition(":")
    if base.startswith("gemma") and base[5:].isdigit():
        return f"Gemma {base[5:]} {tag.upper()}".strip()
    return model


def schema() -> dict:
    return GemmaPick.model_json_schema()


def user_prompt(prefs: Prefs, weather_line: str, window: TimeWindow | None, candidates: list[Candidate]) -> str:
    company = "alone" if prefs.company == "solo" else "with other people"
    lines = [
        f"Mood: {prefs.mood}. Energy: {prefs.energy}. Going {company}. Time available: {prefs.minutes} minutes in total.",
        f"Weather: {weather_line}.",
        task_style(prefs),
    ]
    if window is not None:
        if window.mode == "after_dark":
            lines.append("It will be dark outside. Keep it simple and stay together in busy, lit areas.")
        elif window.mode == "later":
            lines.append("This is for early morning, just after sunrise.")
        if window.rain_risk:
            lines.append("Rain is likely. Suggest something that works under cover or in light rain.")
    lines.append("Places (id | name | kind | walk one way | direction | max minutes there):")
    for c in candidates:
        kind = c.place.kind.replace("_", " ")
        lines.append(
            f"{c.id} | {c.place.label} | {kind} | {c.walk_min} min | {c.direction} | {prefs.minutes - 2 * c.walk_min}"
        )
    return "\n".join(lines)


def messages(prefs: Prefs, weather_line: str, window: TimeWindow | None, candidates: list[Candidate]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt(prefs, weather_line, window, candidates)},
    ]


class GemmaError(Exception):
    pass


async def chat(client: httpx.AsyncClient, msgs: list[dict]) -> tuple[str, float]:
    """One call. Returns (raw content, latency seconds)."""
    body = {
        "model": MODEL,
        "messages": msgs,
        "stream": False,
        "think": False,
        "format": schema(),
        # num_predict caps a runaway answer (gemma3:1b once wrote 6.8k chars in 45 s).
        "options": {"temperature": 0.7, "num_ctx": 4096, "num_predict": 400},
    }
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=TIMEOUT_S)
        r.raise_for_status()
        content = r.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise GemmaError(f"Ollama call failed: {exc!r}") from exc
    return content, time.perf_counter() - t0


def retry_messages(msgs: list[dict], raw: str, reason: str) -> list[dict]:
    return [
        *msgs,
        {"role": "assistant", "content": raw},
        {"role": "user", "content": f"That answer was rejected: {reason} Return a corrected JSON object."},
    ]


async def health(client: httpx.AsyncClient) -> dict:
    """Is Ollama up, and is the model pulled?"""
    try:
        r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return {"ollama": False, "model": MODEL, "model_present": False}
    return {"ollama": True, "model": MODEL, "model_present": MODEL in names}


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
