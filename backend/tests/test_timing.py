from datetime import datetime, timedelta, timezone

import pytest

from logoff.models import Weather
from logoff.timing import (
    fmt_time,
    max_precip,
    plan_window,
    round_up_5,
    walk_minutes,
    with_outing,
)

TZ = timezone(timedelta(hours=5, minutes=30))
DAY = datetime(2026, 10, 12, tzinfo=TZ)


def at(h: int, m: int = 0, day: datetime = DAY) -> datetime:
    return day.replace(hour=h, minute=m)


def weather(rain: dict[int, int] | None = None) -> Weather:
    """Sunrise 6:15, sunset 18:12 today; 6:16 / 18:11 tomorrow. rain: {hour_today: pct}."""
    rain = rain or {}
    hourly = [(at(0) + timedelta(hours=h), rain.get(h, 5)) for h in range(48)]
    return Weather(
        temp_c=29, feels_c=33, code=2, description="partly cloudy", is_day=True,
        sunrise_today=at(6, 15), sunset_today=at(18, 12),
        sunrise_tomorrow=at(6, 16) + timedelta(days=1), sunset_tomorrow=at(18, 11) + timedelta(days=1),
        hourly_precip=hourly,
    )


@pytest.mark.parametrize("metres,minutes", [(0, 1), (10, 1), (577, 11), (600, 11), (1000, 18)])
def test_walk_minutes(metres, minutes):
    # ceil(m * 1.3 / 75), at least 1
    assert walk_minutes(metres) == minutes


def test_round_up_5():
    assert round_up_5(at(17, 0)) == at(17, 0)
    assert round_up_5(at(17, 1)) == at(17, 5)
    assert round_up_5(at(17, 5).replace(second=1)) == at(17, 10)
    assert round_up_5(at(23, 58)) == at(0, 0, DAY + timedelta(days=1))


def test_fmt_time():
    assert fmt_time(at(17, 5)) == "5:05 PM"
    assert fmt_time(at(0, 30)) == "12:30 AM"
    assert fmt_time(at(12, 0)) == "12:00 PM"
    assert fmt_time(at(9, 45)) == "9:45 AM"


def test_daytime_goes_now():
    w = plan_window(at(16, 2), 30, weather(), "solo")
    assert w.mode == "now"
    assert w.leave_by == at(16, 5)
    assert w.back_by == at(16, 35)
    assert w.latest_leave == at(17, 37)  # 18:12 - 30 - 5
    assert "6:12 PM" in w.note


def test_just_before_latest_leave_still_now():
    w = plan_window(at(17, 35), 30, weather(), "solo")  # latest leave 17:37
    assert w.mode == "now"


def test_rounding_past_latest_leave_is_too_late():
    w = plan_window(at(17, 37), 30, weather(), "solo")  # rounds up to 17:40
    assert w.mode == "later"


def test_too_close_to_sunset_solo_goes_tomorrow():
    w = plan_window(at(17, 50), 30, weather(), "solo")
    assert w.mode == "later"
    assert w.leave_by == at(6, 20, DAY + timedelta(days=1))
    assert w.back_by == at(6, 50, DAY + timedelta(days=1))
    assert "tomorrow morning" in w.note


def test_after_sunset_with_others_goes_after_dark():
    w = plan_window(at(19, 3), 45, weather(), "others")
    assert w.mode == "after_dark"
    assert w.leave_by == at(19, 5)
    assert w.latest_leave is None


def test_before_sunrise_solo_waits_for_this_mornings_sunrise():
    w = plan_window(at(3, 40), 15, weather(), "solo")
    assert w.mode == "later"
    assert w.leave_by == at(6, 15)
    assert "this morning" in w.note


def test_rain_risk_flagged_and_explained():
    w = plan_window(at(15, 0), 60, weather({15: 70}), "solo")
    assert w.rain_risk is True
    assert w.rain_max_pct == 70
    assert "70% chance of rain" in w.note


def test_rain_outside_window_ignored():
    w = plan_window(at(15, 0), 30, weather({17: 90}), "solo")
    assert w.rain_risk is False


def test_max_precip_overlap():
    wx = weather({14: 40, 15: 65})
    assert max_precip(wx, at(14, 30), at(15, 10)) == 65
    assert max_precip(wx, at(14, 0), at(14, 50)) == 40


def test_no_weather_still_plans():
    w = plan_window(at(16, 2), 30, None, "solo")
    assert w.mode == "now"
    assert w.sunset is None
    assert "No weather data" in w.note


def test_with_outing_recomputes_back_by():
    w = with_outing(plan_window(at(16, 0), 60, weather(), "solo"), 25)
    assert w.back_by == at(16, 25)
