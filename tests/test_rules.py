"""Unit tests for the rule engine (pure functions, mutation-testing target)."""

from __future__ import annotations

from custom_components.ghandalf.const import (
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_SURPLUS_THRESHOLD_W,
)
from custom_components.ghandalf.models import Category, Urgency
from custom_components.ghandalf.rules import (
    _exporting_w,
    evaluate_rules,
    rule_dehumidifier,
    rule_solar_surplus,
)

_CFG = {CONF_SURPLUS_THRESHOLD_W: 1000}


def _rooms(*pairs):
    """Build a snapshot. Each pair is (name, humidity) or (name, humidity, power_w)."""
    rooms = []
    for p in pairs:
        name, humidity = p[0], p[1]
        power_w = p[2] if len(p) > 2 else None
        rooms.append(
            {
                "entity_id": f"sensor.{name.lower()}",
                "name": name,
                "humidity": humidity,
                "power_w": power_w,
            }
        )
    return {"dehumidifier_rooms": rooms}


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


def test_dehumidifier_fires_only_for_humid_rooms():
    snap = _rooms(("Bathroom", 65.0), ("Basement", 58.0), ("Attic", None))
    out = rule_dehumidifier(snap, {CONF_HUMIDITY_THRESHOLD_PCT: 60})
    assert [c.data["room"] for c in out] == ["Bathroom"]
    c = out[0]
    assert c.key == "dehumidifier:sensor.bathroom"
    assert c.category is Category.AIR_QUALITY
    assert c.urgency is Urgency.ACT
    assert c.message.startswith("Humidity in Bathroom is 65%")
    assert c.message.endswith("Time to run the dehumidifier.")
    assert "above 60%" in c.message
    assert c.data["humidity"] == 65.0
    assert c.data["threshold"] == 60


def test_dehumidifier_skipped_room_does_not_block_later_room():
    # A dry room listed first must not stop a humid room listed after it.
    out = rule_dehumidifier(
        _rooms(("Dry", 50.0), ("Wet", 70.0)), {CONF_HUMIDITY_THRESHOLD_PCT: 60}
    )
    assert [c.data["room"] for c in out] == ["Wet"]


def test_dehumidifier_suppressed_when_already_running():
    cfg = {CONF_HUMIDITY_THRESHOLD_PCT: 60, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
    # humid (70%) but plug drawing 250 W -> already running -> no advice
    assert rule_dehumidifier(_rooms(("Base", 70.0, 250.0)), cfg) == []


def test_dehumidifier_fires_when_plug_idle():
    cfg = {CONF_HUMIDITY_THRESHOLD_PCT: 60, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
    out = rule_dehumidifier(_rooms(("Base", 70.0, 2.0)), cfg)  # 2 W = off
    assert [c.data["room"] for c in out] == ["Base"]
    assert out[0].data["power_w"] == 2.0


def test_dehumidifier_running_boundary_counts_as_running():
    cfg = {CONF_HUMIDITY_THRESHOLD_PCT: 60, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
    # Exactly at the running threshold counts as running -> suppressed.
    assert rule_dehumidifier(_rooms(("Base", 70.0, 10.0)), cfg) == []


def test_dehumidifier_running_room_does_not_block_later_room():
    cfg = {CONF_HUMIDITY_THRESHOLD_PCT: 60, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
    out = rule_dehumidifier(
        _rooms(("Running", 70.0, 250.0), ("Idle", 70.0, 2.0)), cfg
    )
    assert [c.data["room"] for c in out] == ["Idle"]


def test_dehumidifier_fires_when_power_unknown():
    # No paired plug -> can't tell -> advise (safe default).
    out = rule_dehumidifier(
        _rooms(("Base", 70.0, None)), {CONF_HUMIDITY_THRESHOLD_PCT: 60}
    )
    assert len(out) == 1
    assert out[0].data["power_w"] is None


def test_dehumidifier_running_uses_default_watts():
    # No running-watts in cfg -> default 10; 50 W counts as running -> suppressed.
    assert rule_dehumidifier(_rooms(("Base", 70.0, 50.0)), {}) == []


def test_dehumidifier_message_drops_trailing_zero():
    out = rule_dehumidifier(_rooms(("R", 70.0)), {CONF_HUMIDITY_THRESHOLD_PCT: 55.0})
    assert "above 55%" in out[0].message
    assert "55.0" not in out[0].message


def test_dehumidifier_fires_at_exact_threshold():
    out = rule_dehumidifier(_rooms(("R", 60.0)), {CONF_HUMIDITY_THRESHOLD_PCT: 60})
    assert len(out) == 1


def test_dehumidifier_uses_default_threshold():
    assert len(rule_dehumidifier(_rooms(("R", 61.0)), {})) == 1  # default 60
    assert rule_dehumidifier(_rooms(("R", 59.0)), {}) == []


def test_dehumidifier_handles_no_rooms():
    assert rule_dehumidifier({}, {}) == []
    assert rule_dehumidifier({"dehumidifier_rooms": []}, {}) == []


def test_dehumidifier_multiple_humid_rooms():
    out = rule_dehumidifier(_rooms(("A", 70.0), ("B", 80.0)), {})
    assert {c.data["room"] for c in out} == {"A", "B"}


def test_evaluate_rules_collects_single_and_multi():
    snap = {"net_grid_w": -3000.0, "surplus_w": 3000.0, **_rooms(("Bath", 75.0))}
    keys = {a.key for a in evaluate_rules(snap, _CFG)}
    assert keys == {"solar_surplus", "dehumidifier:sensor.bath"}

    none = evaluate_rules({"net_grid_w": 0.0, "surplus_w": 0.0}, _CFG)
    assert none == []
