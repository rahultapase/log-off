import math

import pytest

from logoff.geo import (
    bbox_area_m2,
    bearing_deg,
    compass,
    haversine_m,
    nearest_street,
    polygon_area_m2,
    round_coord,
)

# Synthetic points on the equator / a meridian; no real user locations in tests.
ONE_DEG_M = 2 * math.pi * 6_371_008.8 / 360  # ~111.2 km


def test_haversine_zero():
    assert haversine_m(10.0, 20.0, 10.0, 20.0) == 0


def test_haversine_one_degree_latitude():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(ONE_DEG_M, rel=1e-6)


def test_haversine_symmetric():
    a = haversine_m(10.0, 20.0, 10.01, 20.02)
    b = haversine_m(10.01, 20.02, 10.0, 20.0)
    assert a == pytest.approx(b)


@pytest.mark.parametrize(
    "dlat,dlon,expected",
    [(0.01, 0, 0), (0, 0.01, 90), (-0.01, 0, 180), (0, -0.01, 270)],
)
def test_bearing_cardinal(dlat, dlon, expected):
    b = bearing_deg(0, 0, dlat, dlon)
    assert b == pytest.approx(expected, abs=0.01)


def test_bearing_north_east():
    assert bearing_deg(0, 0, 0.01, 0.01) == pytest.approx(45, abs=0.1)


@pytest.mark.parametrize(
    "deg,label",
    [(0, ("north", "N")), (22.4, ("north", "N")), (22.5, ("north-east", "NE")),
     (90, ("east", "E")), (200, ("south", "S")), (315, ("north-west", "NW")),
     (337.6, ("north", "N")), (359.9, ("north", "N"))],
)
def test_compass(deg, label):
    assert compass(deg) == label


def test_round_coord_three_dp():
    assert round_coord(12.345678) == 12.346
    assert round_coord(-0.0004) == 0.0


def test_polygon_area_square():
    # ~111 m x ~111 m square at the equator
    d = 0.001
    sq = [(0, 0), (0, d), (d, d), (d, 0)]
    side = ONE_DEG_M * d
    assert polygon_area_m2(sq) == pytest.approx(side * side, rel=0.01)
    assert bbox_area_m2(0, 0, d, d) == pytest.approx(side * side, rel=0.01)


def test_polygon_area_degenerate():
    assert polygon_area_m2([(0, 0), (0, 1)]) == 0


def test_nearest_street_picks_closest_within_limit():
    streets = [
        ("Far Road", [(0.01, 0.01)]),
        ("Near Lane", [(0.0005, 0.0), (0.001, 0.0)]),
    ]
    assert nearest_street(0, 0, streets) == "Near Lane"
    assert nearest_street(0, 0, [("Far Road", [(0.01, 0.01)])]) is None
