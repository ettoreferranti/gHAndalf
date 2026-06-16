"""Unit tests for the rule engine (pure functions, mutation-testing target)."""

from __future__ import annotations

from custom_components.ghandalf.const import CONF_SURPLUS_THRESHOLD_W
from custom_components.ghandalf.models import Category, Urgency
from custom_components.ghandalf.rules import (
    _exporting_w,
    evaluate_rules,
    rule_solar_surplus,
)

_CFG = {CONF_SURPLUS_THRESHOLD_W: 1000}


def test_exporting_w_clamps_import_to_zero():
    assert _exporting_w({"net_grid_w": 2000.0, "surplus_w": -2000.0}) == 0.0
    assert _exporting_w({"net_grid_w": -800.0}) == 800.0
    assert _exporting_w({"net_grid_w": None, "surplus_w": -50.0}) == 0.0
    assert _exporting_w({"net_grid_w": None, "surplus_w": 1500.0}) == 1500.0
    assert _exporting_w({"net_grid_w": None, "surplus_w": None}) is None


def test_surplus_fires_when_exporting_above_threshold():
    snap = {"net_grid_w": -3000.0, "surplus_w": 5000.0}
    advice = rule_solar_surplus(snap, _CFG)
    assert advice is not None
    assert advice.key == "solar_surplus"
    assert advice.category is Category.ENERGY
    assert advice.urgency is Urgency.INFO
    assert advice.message.startswith("You're sending about 3000 W")
    assert advice.message.endswith("top up the car.")
    assert advice.data["exporting_w"] == 3000.0
    assert advice.data["threshold_w"] == 1000


def test_surplus_fires_exactly_at_threshold():
    # We fire when exporting >= threshold; the boundary must count.
    advice = rule_solar_surplus({"net_grid_w": -1000.0, "surplus_w": 1000.0}, _CFG)
    assert advice is not None


def test_surplus_silent_below_threshold():
    snap = {"net_grid_w": -500.0, "surplus_w": 500.0}
    assert rule_solar_surplus(snap, _CFG) is None


def test_surplus_silent_when_importing():
    snap = {"net_grid_w": 2000.0, "surplus_w": -2000.0}
    assert rule_solar_surplus(snap, _CFG) is None


def test_surplus_prefers_net_grid_over_raw_surplus():
    # Battery is absorbing the surplus: PV-minus-consumption is high, but little
    # is actually exported, so we should NOT nudge to use it.
    snap = {"net_grid_w": -100.0, "surplus_w": 4000.0}
    assert rule_solar_surplus(snap, _CFG) is None


def test_surplus_falls_back_to_raw_when_no_grid():
    snap = {"net_grid_w": None, "surplus_w": 2500.0}
    advice = rule_solar_surplus(snap, _CFG)
    assert advice is not None
    assert advice.data["exporting_w"] == 2500.0


def test_surplus_none_when_nothing_known():
    assert rule_solar_surplus({"net_grid_w": None, "surplus_w": None}, _CFG) is None


def test_surplus_uses_default_threshold_when_unset():
    # No threshold in cfg -> default 1000; 1500 exported should fire.
    advice = rule_solar_surplus({"net_grid_w": -1500.0, "surplus_w": 1500.0}, {})
    assert advice is not None


def test_evaluate_rules_collects_candidates():
    advice = evaluate_rules({"net_grid_w": -3000.0, "surplus_w": 3000.0}, _CFG)
    assert [a.key for a in advice] == ["solar_surplus"]

    none = evaluate_rules({"net_grid_w": 0.0, "surplus_w": 0.0}, _CFG)
    assert none == []
