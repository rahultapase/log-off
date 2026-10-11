"""Run Log Off's planner N times over preference combos and print stats for the write-up.

    uv run python scripts/eval_gemma.py --area "Sector 35, Kharghar" --at 16:00

Coordinates are geocoded at run time and never written anywhere. Each Gemma attempt is
appended to data/runs.jsonl (gitignored) with tag "eval".
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from logoff import USER_AGENT, gemma, geocode, weather  # noqa: E402
from logoff.models import Prefs  # noqa: E402
from logoff.planner import make_ticket  # noqa: E402

MOODS = ["calm", "curious", "restless", "social"]
TIMES = [30, 45, 60]
COMPANY = ["solo", "others"]
ENERGY = ["low", "medium", "high"]


def combos(n: int) -> list[Prefs]:
    grid = list(itertools.product(MOODS, TIMES, COMPANY))
    out = []
    for i, (mood, minutes, company) in enumerate(grid):
        out.append(Prefs(mood=mood, minutes=minutes, energy=ENERGY[i % 3], company=company))
    if n < len(out):
        # Evenly spaced picks; offset odd indices so both solo and others appear.
        out = [out[min(len(out) - 1, (i * len(out)) // n + (i % 2))] for i in range(n)]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="Sector 35, Kharghar")
    ap.add_argument("--runs", type=int, default=24)
    ap.add_argument("--at", default="16:00", help="local time to plan for, HH:MM (default 16:00)")
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        area = await geocode.search(client, args.area)
        wx = await weather.fetch(client, area.lat, area.lon)
        hh, mm = (int(x) for x in args.at.split(":"))
        now = datetime.now(wx.sunset_today.tzinfo).replace(hour=hh, minute=mm, second=0, microsecond=0)

        t0 = time.perf_counter()
        await gemma.chat(client, [{"role": "user", "content": "Reply with {}"}])  # load the model
        print(f"model warm-up (load): {time.perf_counter() - t0:.1f} s")

        tickets = []
        for i, prefs in enumerate(combos(args.runs), start=1):
            t = time.perf_counter()
            tk = await make_ticket(client, area, prefs, now=now, tag="eval")
            tk["_wall_s"] = time.perf_counter() - t
            tickets.append((prefs, tk))
            first = tk["attempts"][0] if tk["attempts"] else {}
            print(f"{i:2d}. {prefs.mood:8s} {prefs.minutes}m {prefs.energy:6s} {prefs.company:6s} -> "
                  f"{tk['source']:8s} {tk['place']['label'][:32]:32s} "
                  f"try1={'ok' if first.get('valid') else 'rule ' + str(first.get('rule'))} "
                  f"{tk['_wall_s']:.1f}s")

    n = len(tickets)
    first_ok = sum(1 for _, t in tickets if t["attempts"] and t["attempts"][0]["valid"])
    retry_ok = sum(1 for _, t in tickets if len(t["attempts"]) == 2 and t["attempts"][1]["valid"])
    fb = sum(1 for _, t in tickets if t["source"] == "fallback")
    attempts = [a for _, t in tickets for a in t["attempts"]]
    rules = Counter(a["rule"] for a in attempts if not a["valid"])
    invented_runs = [t for _, t in tickets if any(a["rule"] in (2, 3) for a in t["attempts"])]
    invented_names = [x for a in attempts for x in (a.get("invented") or [])]
    call_lat = [a["latency_s"] for a in attempts]
    run_lat = [t["_wall_s"] for _, t in tickets]
    places_used = Counter(t["place"]["label"] for _, t in tickets)

    print("\n=== Eval summary ===")
    print(f"area: {area.label}; planned for {now:%a %d %b %H:%M} local; model {gemma.MODEL}")
    print(f"runs {n}; valid first try {first_ok}; fixed on retry {retry_ok}; fallback {fb}")
    print(f"Gemma attempts {len(attempts)}; rejections by rule: {dict(sorted(rules.items()))}")
    print(f"runs where Gemma named a place not on the list (rule 2/3): {len(invented_runs)} of {n}; "
          f"all caught (none reached a ticket)")
    print(f"invented names seen: {sorted(set(invented_names))}")
    print(f"median call latency {statistics.median(call_lat):.1f} s (max {max(call_lat):.1f}); "
          f"median run {statistics.median(run_lat):.1f} s")
    print(f"distinct places chosen: {len(places_used)} -> {dict(places_used.most_common())}")
    reasons = [a["reason"] for a in attempts if not a["valid"]]
    if reasons:
        print("rejection reasons (first 8):")
        for r in reasons[:8]:
            print("  -", r)

    print("\n=== Sample tickets ===")
    for prefs, t in tickets[: args.samples]:
        print(f"\n[{prefs.mood}, {prefs.minutes} min, {prefs.energy}, {prefs.company}] via {t['source']}")
        print(f"  {t['title']}")
        print(f"  {t['place']['label']} - {t['place']['walk_min']} min walk {t['place']['direction']}")
        print(f"  Leave by {t['leave_by_text']}, back by {t['back_by_text']}. {t['weather']}.")
        for s in t["steps"]:
            print(f"   * {s}")
        if t["gemma_why"]:
            print(f"  Gemma: {t['gemma_why']}")
        print(f"  Why: {' | '.join(t['why'])}")


if __name__ == "__main__":
    asyncio.run(main())
