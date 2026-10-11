"""Every validator rule, fed hand-written bad outputs."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from logoff.fallback import activity
from logoff.models import Candidate, Place, Prefs, TimeWindow
from logoff.validate import check, invented_names, render

TZ = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=TZ)


def cand(i, label, walk, kind="park", named=True):
    p = Place(osm_id=f"way/{i}", name=label if named else None, kind=kind, lat=0, lon=0,
              label=label, named=named, area_m2=5000)
    return Candidate(id=f"P{i}", place=p, distance_m=walk * 58, walk_min=walk,
                     bearing_deg=45, direction="north-east", direction_short="NE")


CANDS = [cand(1, "Hasta Mudra Park", 8), cand(2, "Unnamed park off Raghunath Road", 5, named=False),
         cand(3, "ISCKON", 12, kind="place_of_worship")]
PREFS = Prefs(mood="calm", minutes=30, energy="low", company="solo")


def window(mode="now", rain=False):
    return TimeWindow(mode=mode, leave_by=NOW, back_by=NOW + timedelta(minutes=30), latest_leave=None,
                      sunset=NOW + timedelta(hours=2), rain_max_pct=70 if rain else 5, rain_risk=rain, note="")


def good(**over):
    base = {
        "place_id": "P1",
        "title": "Five sounds at {place}",
        "steps": ["Walk to {place} slowly.", "Find the quietest bench.", "Count five different sounds."],
        "duration_min": 12,
        "why": "A park is quiet enough to slow down.",
    }
    base.update(over)
    return json.dumps(base)


def test_good_answer_passes():
    v = check(good(), CANDS, PREFS, window())
    assert v.ok, v.reason


def test_rule1_invalid_json():
    v = check("{not json", CANDS, PREFS, window())
    assert not v.ok and v.rule == 1


def test_rule1_schema_too_few_steps():
    v = check(good(steps=["Just one step."]), CANDS, PREFS, window())
    assert not v.ok and v.rule == 1 and "steps" in v.reason


def test_rule1_missing_field():
    v = check(json.dumps({"place_id": "P1", "title": "x y z"}), CANDS, PREFS, window())
    assert not v.ok and v.rule == 1


def test_rule2_unknown_place_id():
    v = check(good(place_id="P9"), CANDS, PREFS, window())
    assert not v.ok and v.rule == 2 and "P1, P2, P3" in v.reason


@pytest.mark.parametrize("text,bad", [
    ("Walk to Central Park and sit.", "Central Park"),
    ("Then head to Sector 21 Garden for tea.", "Sector 21"),
    ("Stop by the Shiv Temple on the way.", "Shiv Temple"),
    ("Look for the old Banyan Tree.", "Banyan Tree"),
    ("Cross Palm Beach Road carefully.", "Palm Beach Road"),
])
def test_rule3_invented_places(text, bad):
    v = check(good(steps=["Walk to {place}.", text]), CANDS, PREFS, window())
    assert not v.ok and v.rule == 3 and bad in v.reason


def test_rule3_numbered_label_on_list_is_fine():
    cands = [*CANDS, cand(4, "Sector-20 Park", 6)]
    assert invented_names("Walk through Sector 20 Park.", [c.place.label for c in cands]) == []


def test_rule3_allows_listed_labels_and_generic_words():
    text = "Visit Hasta Mudra Park. The Park is quiet. Walk past ISCKON. Find the Garden gate."
    assert invented_names(text, [c.place.label for c in CANDS]) == []
    assert invented_names("Leave Raghunath Road behind.", [c.place.label for c in CANDS]) == []


@pytest.mark.parametrize("text", [
    "Walk 2 km to {place}.", "It is 500 metres away.", "Go 300 meters north.",
    "Leave at 5:30 PM.", "Be back by 6 pm.", "Sit there until 17.45.", "Use the {map} app.",
])
def test_rule4_distances_times_and_stray_braces(text):
    v = check(good(steps=["Walk to {place}.", text]), CANDS, PREFS, window())
    assert not v.ok and v.rule == 4


def test_rule5_over_budget():
    # P1 is 8 min each way: 16 + 20 = 36 > 30
    v = check(good(duration_min=20), CANDS, PREFS, window())
    assert not v.ok and v.rule == 5 and "at most 14" in v.reason


def test_rule5_exactly_on_budget_ok():
    assert check(good(duration_min=14), CANDS, PREFS, window()).ok


def test_rule6_never_swim():
    v = check(good(steps=["Walk to {place}.", "Swim across the pond."]), CANDS, PREFS, window())
    assert not v.ok and v.rule == 6


def test_rule6_after_dark():
    bad = good(steps=["Walk to {place}.", "Climb the hill behind it."])
    assert check(bad, CANDS, PREFS, window()).ok
    v = check(bad, CANDS, PREFS, window(mode="after_dark"))
    assert not v.ok and v.rule == 6


def test_rule6_rain():
    bad = good(steps=["Walk to {place}.", "Have a picnic on the lawn."])
    assert check(bad, CANDS, PREFS, window()).ok
    v = check(bad, CANDS, PREFS, window(rain=True))
    assert not v.ok and v.rule == 6


def test_render_substitutes_label():
    v = check(good(), CANDS, PREFS, window())
    r = render(v.pick, "Hasta Mudra Park")
    assert r.title == "Five sounds at Hasta Mudra Park"
    assert r.steps[0] == "Walk to Hasta Mudra Park slowly."


@pytest.mark.parametrize("mood", ["calm", "curious", "restless", "social"])
@pytest.mark.parametrize("company", ["solo", "others"])
def test_fallback_always_passes_validator(mood, company):
    prefs = Prefs(mood=mood, minutes=30, energy="medium", company=company)
    for c in CANDS:
        if 2 * c.walk_min > 30:
            continue
        pick = activity(c, prefs)
        v = check(pick.model_dump(), CANDS, prefs, window())
        assert v.ok, (mood, company, c.place.label, v.reason)
