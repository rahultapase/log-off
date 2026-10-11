from logoff.places import build_places, classify, parse_map_api

STREETS = [("Test Road", [(0.0012, 0.0012)])]


def raw(osm_id, tags, lat=0.001, lon=0.001, area=5000.0):
    return {"osm_id": osm_id, "tags": tags, "lat": lat, "lon": lon, "area": area}


def test_classify():
    assert classify({"leisure": "park"}) == "park"
    assert classify({"tourism": "viewpoint"}) == "viewpoint"
    assert classify({"amenity": "place_of_worship", "name": "T"}) == "place_of_worship"
    assert classify({"leisure": "park", "access": "private"}) is None
    assert classify({"shop": "bakery"}) is None


def test_unnamed_park_labelled_by_street_and_tiny_ones_dropped():
    out = build_places(
        [raw("way/1", {"leisure": "park"}), raw("way/2", {"leisure": "park"}, area=200),
         raw("way/3", {"leisure": "garden"})],
        STREETS, (0.0, 0.0),
    )
    assert [p.label for p in out] == ["Unnamed park off Test Road"]
    assert out[0].named is False


def test_prefers_english_name_and_dedupes_by_name():
    out = build_places(
        [raw("node/1", {"leisure": "park", "name": "X", "name:en": "Central Park"}, area=0),
         raw("way/2", {"leisure": "park", "name": "Central Park"}, area=80_000)],
        STREETS, (0.0, 0.0),
    )
    assert len(out) == 1 and out[0].osm_id == "way/2"


def test_merges_same_kind_mapped_twice_nearby():
    out = build_places(
        [raw("node/1", {"amenity": "place_of_worship", "name": "ISCKON"}, area=0),
         raw("node/2", {"amenity": "place_of_worship", "name": "ISKON"}, lat=0.0015, area=0),
         raw("way/3", {"leisure": "park", "name": "Side Park"}, lat=0.0012)],
        STREETS, (0.0, 0.0),
    )
    assert sorted(p.kind for p in out) == ["park", "place_of_worship"]


def test_drops_beyond_radius():
    out = build_places([raw("way/1", {"leisure": "park", "name": "Far"}, lat=0.05)], STREETS, (0.0, 0.0))
    assert out == []


def test_parse_map_api_centroid_and_streets():
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 0.0, "lon": 0.0},
        {"type": "node", "id": 2, "lat": 0.0, "lon": 0.002},
        {"type": "node", "id": 3, "lat": 0.002, "lon": 0.002},
        {"type": "node", "id": 4, "lat": 0.002, "lon": 0.0},
        {"type": "node", "id": 5, "lat": 0.001, "lon": 0.003, "tags": {"tourism": "viewpoint", "name": "V"}},
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1], "tags": {"leisure": "park", "name": "Sq"}},
        {"type": "way", "id": 11, "nodes": [1, 2], "tags": {"highway": "residential", "name": "A Road"}},
    ]}
    places, streets = parse_map_api(payload)
    sq = next(p for p in places if p["osm_id"] == "way/10")
    assert abs(sq["lat"] - 0.001) < 1e-9 and abs(sq["lon"] - 0.001) < 1e-9
    assert sq["area"] > 40_000
    assert any(p["osm_id"] == "node/5" for p in places)
    assert streets == [("A Road", [(0.0, 0.0), (0.0, 0.002)])]
