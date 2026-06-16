"""Unit tests for the rule engine (pure functions, mutation-testing target)."""

from __future__ import annotations

from custom_components.ghandalf.const import (
    CONF_CO2_THRESHOLD_PPM,
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_HUMIDITY_OFF_THRESHOLD_PCT,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_SURPLUS_THRESHOLD_W,
)
from custom_components.ghandalf.models import Category, Urgency
from custom_components.ghandalf.rules import (
    _exporting_w,
    evaluate_rules,
    rule_co2_ventilate,
    rule_dehumidifier,
    rule_dehumidifier_off,
    rule_solar_surplus,
)

_OFF = {CONF_HUMIDITY_OFF_THRESHOLD_PCT: 45, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
_CO2 = {CONF_CO2_THRESHOLD_PPM: 1000}


def _co2_snap(*rooms, outdoor=None):
    """Each room is (name, ppm) or (name, ppm, window_open)."""
    out = []
    for r in rooms:
        window_open = r[2] if len(r) > 2 else False
        out.append(
            {
                "entity_id": f"sensor.{r[0].lower()}",
                "name": r[0],
                "ppm": r[1],
                "window_open": window_open,
            }
        )
    return {"co2_rooms": out, "outdoor_temp": outdoor}


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
    snap = _rooms(("Running", 70.0, 250.0), ("Idle", 70.0, 2.0))
    out = rule_dehumidifier(snap, cfg)
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


def test_off_fires_when_dry_and_running():
    out = rule_dehumidifier_off(_rooms(("Base", 40.0, 250.0)), _OFF)
    assert [c.data["room"] for c in out] == ["Base"]
    c = out[0]
    assert c.key == "dehumidifier_off:sensor.base"
    assert c.category is Category.AIR_QUALITY
    assert c.urgency is Urgency.INFO
    assert c.message.startswith("Humidity in Base is 40%")
    assert c.message.endswith("switch the dehumidifier off.")
    assert c.data["power_w"] == 250.0
    assert c.data["off_threshold"] == 45
    assert c.data["humidity"] == 40.0


def test_off_silent_when_dry_but_not_running():
    assert rule_dehumidifier_off(_rooms(("Base", 40.0, 2.0)), _OFF) == []


def test_off_silent_when_power_unknown():
    assert rule_dehumidifier_off(_rooms(("Base", 40.0, None)), _OFF) == []


def test_off_silent_when_not_dry():
    assert rule_dehumidifier_off(_rooms(("Base", 55.0, 250.0)), _OFF) == []


def test_off_silent_when_humidity_unknown():
    assert rule_dehumidifier_off(_rooms(("Base", None, 250.0)), _OFF) == []


def test_off_fires_at_humidity_boundary():
    assert len(rule_dehumidifier_off(_rooms(("Base", 45.0, 250.0)), _OFF)) == 1


def test_off_running_boundary_counts_as_running():
    assert len(rule_dehumidifier_off(_rooms(("Base", 40.0, 10.0)), _OFF)) == 1


def test_off_uses_default_thresholds():
    # No off-threshold/running-watts in cfg -> defaults 45 / 10.
    assert len(rule_dehumidifier_off(_rooms(("Base", 44.0, 50.0)), {})) == 1
    assert rule_dehumidifier_off(_rooms(("Base", 50.0, 50.0)), {}) == []  # not dry
    assert rule_dehumidifier_off(_rooms(("Base", 40.0, 5.0)), {}) == []  # not running


def test_off_humid_room_does_not_block_later_room():
    snap = _rooms(("Humid", 55.0, 250.0), ("Dry", 40.0, 250.0))
    assert [c.data["room"] for c in rule_dehumidifier_off(snap, _OFF)] == ["Dry"]


def test_off_idle_room_does_not_block_later_room():
    snap = _rooms(("Idle", 40.0, 2.0), ("Running", 40.0, 250.0))
    assert [c.data["room"] for c in rule_dehumidifier_off(snap, _OFF)] == ["Running"]


def test_off_and_run_are_mutually_exclusive():
    # Dry + running -> only "off"; humid + not running -> only "run".
    run_cfg = {CONF_HUMIDITY_THRESHOLD_PCT: 60, **_OFF}
    dry = _rooms(("Base", 40.0, 250.0))
    assert rule_dehumidifier(dry, run_cfg) == []
    assert len(rule_dehumidifier_off(dry, run_cfg)) == 1


def test_evaluate_rules_includes_off_rule():
    snap = {"net_grid_w": 0.0, "surplus_w": 0.0, **_rooms(("Base", 40.0, 250.0))}
    keys = {a.key for a in evaluate_rules(snap, _OFF)}
    assert "dehumidifier_off:sensor.base" in keys


def test_co2_fires_when_high_and_window_closed():
    out = rule_co2_ventilate(_co2_snap(("Office", 1200.0)), _CO2)
    assert [c.data["room"] for c in out] == ["Office"]
    c = out[0]
    assert c.key == "co2:sensor.office"
    assert c.category is Category.AIR_QUALITY
    assert c.urgency is Urgency.ACT
    assert c.message.startswith("CO2 in Office is 1200 ppm")
    assert c.message.endswith("freshen the air.")
    assert c.data["ppm"] == 1200.0
    assert c.data["threshold"] == 1000


def test_co2_silent_below_threshold():
    assert rule_co2_ventilate(_co2_snap(("Office", 800.0)), _CO2) == []


def test_co2_fires_at_threshold_boundary():
    assert len(rule_co2_ventilate(_co2_snap(("Office", 1000.0)), _CO2)) == 1


def test_co2_silent_when_window_open():
    assert rule_co2_ventilate(_co2_snap(("Office", 1500.0, True)), _CO2) == []


def test_co2_silent_when_ppm_unknown():
    assert rule_co2_ventilate(_co2_snap(("Office", None)), _CO2) == []


def test_co2_uses_default_threshold():
    assert len(rule_co2_ventilate(_co2_snap(("Office", 1100.0)), {})) == 1  # default
    assert rule_co2_ventilate(_co2_snap(("Office", 900.0)), {}) == []


def test_co2_message_includes_outdoor_temp_when_present():
    out = rule_co2_ventilate(_co2_snap(("Office", 1200.0), outdoor=18.4), _CO2)
    assert out[0].message.startswith("CO2 in Office")  # the CO2 part is kept
    assert out[0].message.endswith("It's about 18° outside.")
    assert out[0].data["outdoor_temp"] == 18.4


def test_co2_message_omits_outdoor_when_absent():
    out = rule_co2_ventilate(_co2_snap(("Office", 1200.0), outdoor=None), _CO2)
    assert "outside" not in out[0].message
    assert out[0].data["outdoor_temp"] is None


def test_co2_fresh_room_does_not_block_later_room():
    snap = _co2_snap(("Fresh", 800.0), ("Stuffy", 1300.0))
    assert [c.data["room"] for c in rule_co2_ventilate(snap, _CO2)] == ["Stuffy"]


def test_co2_vented_room_does_not_block_later_room():
    snap = _co2_snap(("Vented", 1300.0, True), ("Stuffy", 1300.0, False))
    assert [c.data["room"] for c in rule_co2_ventilate(snap, _CO2)] == ["Stuffy"]


def test_co2_no_rooms():
    assert rule_co2_ventilate({}, {}) == []
    assert rule_co2_ventilate({"co2_rooms": []}, {}) == []


def test_evaluate_rules_includes_co2():
    snap = {"net_grid_w": 0.0, "surplus_w": 0.0, **_co2_snap(("Office", 1200.0))}
    keys = {a.key for a in evaluate_rules(snap, _CO2)}
    assert "co2:sensor.office" in keys


def test_evaluate_rules_collects_single_and_multi():
    snap = {"net_grid_w": -3000.0, "surplus_w": 3000.0, **_rooms(("Bath", 75.0))}
    keys = {a.key for a in evaluate_rules(snap, _CFG)}
    assert keys == {"solar_surplus", "dehumidifier:sensor.bath"}

    none = evaluate_rules({"net_grid_w": 0.0, "surplus_w": 0.0}, _CFG)
    assert none == []
