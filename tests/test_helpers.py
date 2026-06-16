"""Unit tests for the pure helper functions (also the mutation-testing target)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.ghandalf.helpers import (
    get_conf,
    net_grid_w,
    parse_float,
    solar_surplus_w,
)


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
