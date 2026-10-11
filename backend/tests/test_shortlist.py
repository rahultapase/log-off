from logoff.models import Place, Prefs
from logoff.shortlist import fits, shortlist

# Synthetic grid around (0, 0); 0.001 deg lat is ~111 m.
ORIGIN = (0.0, 0.0)


def place(osm_id, kind, dlat, dlon=0.0, name="X", area=5000.0):
    return Place(
        osm_id=osm_id, name=name, kind=kind, lat=dlat, lon=dlon,
        label=name or "Unnamed park off Test Road", named=name is not None, area_m2=area,
    )


def prefs(**kw):
    base = {"mood": "calm", "minutes": 30, "energy": "medium", "company": "solo"}
    base.update(kw)
    return Prefs(**base)


PLACES = [
    place("way/1", "park", 0.002, name="Near Park"),            # ~222 m -> 4 min
    place("way/2", "garden", 0.004, name="Mid Garden"),         # ~445 m -> 8 min
    place("node/3", "viewpoint", 0.0, 0.005, name="Hill View"), # ~556 m -> 10 min, east
    place("node/4", "place_of_worship", -0.003, name="Old Temple"),
    place("way/5", "park", 0.009, name="Far Park", area=90_000),  # ~1.0 km -> 18 min (60 min cap)
    place("way/6", "park", 0.001, 0.001, name=None, area=2000),  # unnamed, ~157 m
]


def test_fits_rule():
    assert fits(9, 30)      # 18 <= 18
    assert not fits(10, 30)
    assert fits(4, 15)
    assert not fits(5, 15)


def test_drops_places_beyond_budget_and_assigns_ids():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=30))
    labels = {c.place.label for c in out}
    assert "Far Park" not in labels and "Hill View" not in labels
    assert [c.id for c in out] == [f"P{i}" for i in range(1, len(out) + 1)]
    assert all(2 * c.walk_min <= 0.6 * 30 for c in out)


def test_sixty_minutes_reaches_far_park():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60, mood="restless"))
    assert "Far Park" in {c.place.label for c in out}


def test_restless_ranks_farther_first():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60, mood="restless", energy="high"))
    assert out[0].place.label == "Far Park"


def test_curious_prefers_viewpoint():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60, mood="curious"))
    assert out[0].place.kind == "viewpoint"


def test_direction_and_minutes():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60, mood="curious"))
    view = next(c for c in out if c.place.label == "Hill View")
    assert view.direction == "east" and view.direction_short == "E"
    assert view.walk_min == 10


def test_after_dark_keeps_named_landmarks_only():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60), after_dark=True)
    assert {c.place.label for c in out} == {"Hill View", "Old Temple", "Far Park"}


def test_rain_puts_nearest_first():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60, mood="restless", energy="high"), rain_risk=True)
    assert out[0].walk_min == min(c.walk_min for c in out)


def test_exclude_and_limit():
    out = shortlist(PLACES, *ORIGIN, prefs(minutes=60), exclude={"way/1"}, limit=3)
    assert len(out) == 3
    assert "way/1" not in {c.place.osm_id for c in out}


def test_kind_variety():
    many = [place(f"way/{i}", "park", 0.001 * i, name=f"Park {i}") for i in range(1, 9)]
    many.append(place("node/99", "water", 0.003, name="Pond"))
    out = shortlist(many, *ORIGIN, prefs(minutes=60), limit=4)
    assert "water" in {c.place.kind for c in out}


def test_empty_when_nothing_fits():
    assert shortlist([place("way/5", "park", 0.012, name="Far Park")], *ORIGIN, prefs(minutes=15)) == []
