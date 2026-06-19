"""Unit tests for the pure helper functions (also the mutation-testing target)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from custom_components.ghandalf.helpers import (
    absolute_humidity,
    get_conf,
    in_quiet_hours,
    net_grid_w,
    next_appliance_state,
    occupied_within,
    parse_float,
    parse_time,
    solar_surplus_w,
)

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def _entry(data: dict, options: dict) -> SimpleNamespace:
    """Minimal stand-in for a ConfigEntry (only .data / .options are read)."""
    return SimpleNamespace(data=data, options=options)


def test_get_conf_options_take_precedence():
    entry = _entry(data={"x": "from_data"}, options={"x": "from_options"})
    assert get_conf(entry, "x") == "from_options"


def test_get_conf_falls_back_to_data():
    entry = _entry(data={"x": "from_data"}, options={})
    assert get_conf(entry, "x") == "from_data"


def test_get_conf_falls_back_to_default():
    entry = _entry(data={}, options={})
    assert get_conf(entry, "missing", "the_default") == "the_default"
    assert get_conf(entry, "missing") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("22:00:00", time(22, 0, 0)),
        ("22:00:45", time(22, 0, 45)),  # seconds must be parsed, not dropped
        ("07:30", time(7, 30, 0)),
        ("9", time(9, 0, 0)),
        (time(6, 15), time(6, 15)),
        (None, None),
        ("", None),
        ("not:a:time", None),
        ("25:00", None),  # hour out of range -> default (None)
    ],
)
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected


def test_parse_time_uses_default():
    assert parse_time(None, time(1, 2)) == time(1, 2)
    assert parse_time("garbage", time(1, 2)) == time(1, 2)


@pytest.mark.parametrize(
    ("now", "start", "end", "expected"),
    [
        # Wrapping window 22:00-07:00
        (time(23, 0), time(22, 0), time(7, 0), True),
        (time(2, 0), time(22, 0), time(7, 0), True),
        (time(22, 0), time(22, 0), time(7, 0), True),  # inclusive start
        (time(7, 0), time(22, 0), time(7, 0), False),  # exclusive end
        (time(12, 0), time(22, 0), time(7, 0), False),
        # Same-day window 09:00-17:00
        (time(12, 0), time(9, 0), time(17, 0), True),
        (time(9, 0), time(9, 0), time(17, 0), True),  # inclusive start
        (time(8, 59), time(9, 0), time(17, 0), False),
        (time(17, 0), time(9, 0), time(17, 0), False),
        # Disabled (zero-length)
        (time(3, 0), time(0, 0), time(0, 0), False),
    ],
)
def test_in_quiet_hours(now, start, end, expected):
    assert in_quiet_hours(now, start, end) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (5, 5.0),
        (5.5, 5.5),
        ("5", 5.0),
        ("5.5", 5.5),
        ("-3.2", -3.2),
        ("  7  ", 7.0),
        ("unknown", None),
        ("unavailable", None),
        ("none", None),
        ("", None),
        ("  ", None),
        ("UNAVAILABLE", None),
        ("not a number", None),
    ],
)
def test_parse_float(raw, expected):
    assert parse_float(raw) == expected


def test_parse_float_returns_float_type():
    result = parse_float("42")
    assert isinstance(result, float)


@pytest.mark.parametrize(
    ("pv", "cons", "expected"),
    [
        (3000.0, 1000.0, 2000.0),
        (1000.0, 1500.0, -500.0),
        (0.0, 0.0, 0.0),
        (None, 1000.0, None),
        (3000.0, None, None),
        (None, None, None),
    ],
)
def test_solar_surplus_w(pv, cons, expected):
    assert solar_surplus_w(pv, cons) == expected


@pytest.mark.parametrize(
    ("imp", "exp", "expected"),
    [
        (1000.0, 0.0, 1000.0),
        (0.0, 800.0, -800.0),
        (200.0, 50.0, 150.0),
        (None, 800.0, -800.0),
        (1000.0, None, 1000.0),
        (None, None, None),
    ],
)
def test_net_grid_w(imp, exp, expected):
    assert net_grid_w(imp, exp) == expected


@pytest.mark.parametrize(
    ("temp_c", "rh_pct", "expected"),
    [
        (20.0, 50.0, 8.64),  # reference: ~8.64 g/m^3
        (0.0, 100.0, 4.85),  # saturated near freezing
        (30.0, 80.0, 24.28),
    ],
)
def test_absolute_humidity(temp_c, rh_pct, expected):
    assert absolute_humidity(temp_c, rh_pct) == pytest.approx(expected, abs=0.01)


def test_absolute_humidity_scales_with_rh():
    # Linear in RH: doubling relative humidity doubles absolute humidity.
    assert absolute_humidity(20.0, 80.0) == pytest.approx(
        2 * absolute_humidity(20.0, 40.0), abs=0.001
    )


@pytest.mark.parametrize(
    ("temp_c", "rh_pct"), [(None, 50.0), (20.0, None), (None, None)]
)
def test_absolute_humidity_missing_input(temp_c, rh_pct):
    assert absolute_humidity(temp_c, rh_pct) is None


@pytest.mark.parametrize(
    ("state", "minutes_ago", "expected"),
    [
        ("on", 999, True),  # on now -> occupied regardless of age
        ("off", 5, True),  # off recently -> still within 15-min grace
        ("off", 15, True),  # exactly at the grace boundary still counts
        ("off", 20, False),  # off too long ago -> gone
        ("unavailable", 1, False),  # can't tell -> not occupied
        ("unknown", 1, False),
    ],
)
def test_occupied_within(state, minutes_ago, expected):
    last_changed = _NOW - timedelta(minutes=minutes_ago)
    assert occupied_within(state, last_changed, _NOW, 15) is expected


def test_occupied_within_off_with_no_timestamp_is_not_occupied():
    assert occupied_within("off", None, _NOW, 15) is False


# --- appliance cycle state machine ------------------------------------------
def test_appliance_running_marks_was_running():
    assert next_appliance_state({}, True, True, None, _NOW) == {
        "was_running": True,
        "awaiting_unload": False,
        "finished_at": None,
    }


def test_appliance_finish_arms_awaiting_unload():
    prev = {"was_running": True, "awaiting_unload": False, "finished_at": None}
    s = next_appliance_state(prev, True, False, None, _NOW)
    assert s == {"was_running": False, "awaiting_unload": True, "finished_at": _NOW}


def test_appliance_idle_never_arms():
    # Never ran (was_running False) and still not running -> nothing waiting.
    s = next_appliance_state({}, True, False, None, _NOW)
    assert s == {"was_running": False, "awaiting_unload": False, "finished_at": None}


def test_appliance_holds_awaiting_through_unknown_reading():
    # Machine drops offline after finishing (running_known False) -> state held.
    prev = {"was_running": False, "awaiting_unload": True, "finished_at": _NOW}
    later = _NOW + timedelta(minutes=20)
    assert next_appliance_state(prev, False, False, None, later) == prev


def test_appliance_door_open_clears_awaiting():
    prev = {"was_running": False, "awaiting_unload": True, "finished_at": _NOW}
    assert next_appliance_state(prev, True, False, True, _NOW) == {
        "was_running": False,
        "awaiting_unload": False,
        "finished_at": None,
    }


def test_appliance_restart_clears_awaiting():
    prev = {"was_running": False, "awaiting_unload": True, "finished_at": _NOW}
    s = next_appliance_state(prev, True, True, None, _NOW)
    assert s == {"was_running": True, "awaiting_unload": False, "finished_at": None}
