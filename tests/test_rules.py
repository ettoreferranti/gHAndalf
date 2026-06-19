"""Unit tests for the rule engine (pure functions, mutation-testing target)."""

from __future__ import annotations

from custom_components.ghandalf.const import (
    CONF_CO2_THRESHOLD_PPM,
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_FEEDIN_RATE,
    CONF_HUMIDITY_OFF_THRESHOLD_PCT,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_PRICE_MARGIN_PCT,
    CONF_REQUIRE_OCCUPANCY,
    CONF_SURPLUS_THRESHOLD_W,
    CONF_VENTILATE_MAX_OUTDOOR_TEMP_C,
    CONF_VENTILATE_MIN_OUTDOOR_TEMP_C,
)
from custom_components.ghandalf.models import Category, Urgency
from custom_components.ghandalf.rules import (
    _exporting_w,
    evaluate_rules,
    rule_co2_ventilate,
    rule_dehumidifier,
    rule_dehumidifier_off,
    rule_grid_price,
    rule_laundry_done,
    rule_solar_surplus,
)

_OFF = {CONF_HUMIDITY_OFF_THRESHOLD_PCT: 45, CONF_DEHUMIDIFIER_RUNNING_WATTS: 10}
_CO2 = {CONF_CO2_THRESHOLD_PPM: 1000}
# The occupancy gate is opt-in, so tests that exercise it enable it explicitly.
_CO2_OCC = {CONF_CO2_THRESHOLD_PPM: 1000, CONF_REQUIRE_OCCUPANCY: True}


def _co2_snap(
    *rooms,
    outdoor=None,
    outdoor_humidity=None,
    indoor_temp=None,
    indoor_humidity=None,
    occupied=True,
):
    """Each room is (name, ppm) or (name, ppm, window_open).

    Indoor temp/humidity (for the moisture gate) and occupancy apply to every
    room; the outdoor values live at the snapshot level.
    """
    out = []
    for r in rooms:
        window_open = r[2] if len(r) > 2 else False
        out.append(
            {
                "entity_id": f"sensor.{r[0].lower()}",
                "name": r[0],
                "ppm": r[1],
                "window_open": window_open,
                "indoor_temp": indoor_temp,
                "indoor_humidity": indoor_humidity,
                "occupied": occupied,
            }
        )
    return {
        "co2_rooms": out,
        "outdoor_temp": outdoor,
        "outdoor_humidity": outdoor_humidity,
    }


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


# --- solar surplus: feed-in saving line -------------------------------------
def _surplus_snap(price=None):
    snap = {"net_grid_w": -3000.0, "surplus_w": 3000.0}
    if price is not None:
        snap["price_now"] = price
    return snap


def test_surplus_savings_line_when_price_and_feedin_known():
    # Import 0.70, feed-in 0.10 -> self-consuming saves 60 Rp/kWh (clean rounding).
    cfg = {CONF_SURPLUS_THRESHOLD_W: 1000, CONF_FEEDIN_RATE: 0.10}
    c = rule_solar_surplus(_surplus_snap(0.70), cfg)
    assert c.message.startswith("You're sending about 3000 W")  # base kept
    assert "top up the car." in c.message
    assert c.message.endswith(
        "Using it now instead of exporting saves about 60 Rp/kWh."
    )
    assert c.data["saved_rp_per_kwh"] == 60


def test_surplus_no_savings_line_without_feedin():
    c = rule_solar_surplus(_surplus_snap(0.21), {CONF_SURPLUS_THRESHOLD_W: 1000})
    assert "saves about" not in c.message
    assert "saved_rp_per_kwh" not in c.data
    assert c.message.endswith("top up the car.")


def test_surplus_no_savings_line_without_price():
    cfg = {CONF_SURPLUS_THRESHOLD_W: 1000, CONF_FEEDIN_RATE: 0.10}
    c = rule_solar_surplus(_surplus_snap(price=None), cfg)
    assert "saves about" not in c.message


def test_surplus_no_savings_line_when_price_not_above_feedin():
    cfg = {CONF_SURPLUS_THRESHOLD_W: 1000, CONF_FEEDIN_RATE: 0.13}
    # Export pays the same as import -> nothing saved (boundary, kills > vs >=).
    assert "saves about" not in rule_solar_surplus(_surplus_snap(0.13), cfg).message
    # Export pays more than import -> nothing saved (kills > vs <).
    assert "saves about" not in rule_solar_surplus(_surplus_snap(0.10), cfg).message


# --- dynamic-tariff price window --------------------------------------------
_PRICE = {CONF_PRICE_MARGIN_PCT: 15}


def _price_snap(price, average):
    return {"price_now": price, "price_avg": average}


def test_grid_price_cheap_fires():
    c = rule_grid_price(_price_snap(0.08, 0.20), _PRICE)  # 60% below average
    assert c.key == "grid_price_cheap"
    assert c.category is Category.ENERGY
    assert c.urgency is Urgency.INFO
    assert c.message.startswith("Electricity is cheap right now (0.08 CHF/kWh, ")
    assert "about 60% below today's average" in c.message
    assert c.message.endswith("dishwasher, laundry, or charging the car.")
    assert c.data == {"price": 0.08, "average": 0.20, "pct_from_avg": -60}


def test_grid_price_expensive_fires():
    c = rule_grid_price(_price_snap(0.32, 0.20), _PRICE)  # 60% above average
    assert c.key == "grid_price_expensive"
    assert c.message.startswith("Electricity is pricey right now (0.32 CHF/kWh, ")
    assert "about 60% above today's average" in c.message
    assert "hold off on big flexible loads if you can" in c.message
    assert c.data == {"price": 0.32, "average": 0.20, "pct_from_avg": 60}


def test_grid_price_silent_when_flat():
    assert rule_grid_price(_price_snap(0.1953, 0.1953), _PRICE) is None


def test_grid_price_silent_within_margin():
    assert rule_grid_price(_price_snap(0.21, 0.20), _PRICE) is None  # +5% < 15%


# Clean boundary numbers (avg 2.0, margin 50% -> exact 1.0 / 3.0) so the <=/>=
# comparisons are tested at the exact edge without float rounding.
_HALF = {CONF_PRICE_MARGIN_PCT: 50}


def test_grid_price_cheap_boundary_fires():
    # Exactly at the threshold (2.0 * 0.5 = 1.0) still counts as cheap.
    assert rule_grid_price(_price_snap(1.0, 2.0), _HALF).key == "grid_price_cheap"
    # Just above the threshold -> silent.
    assert rule_grid_price(_price_snap(1.01, 2.0), _HALF) is None


def test_grid_price_expensive_boundary_fires():
    # Exactly at the threshold (2.0 * 1.5 = 3.0) still counts as pricey.
    assert rule_grid_price(_price_snap(3.0, 2.0), _HALF).key == "grid_price_expensive"
    # 2.995 is below the +50% mark (3.0) but above a 49.5% one — pins the margin math.
    assert rule_grid_price(_price_snap(2.995, 2.0), _HALF) is None


def test_grid_price_none_when_data_missing():
    assert rule_grid_price(_price_snap(None, 0.20), _PRICE) is None
    assert rule_grid_price(_price_snap(0.10, None), _PRICE) is None
    assert rule_grid_price({}, _PRICE) is None


def test_grid_price_none_when_average_not_positive():
    assert rule_grid_price(_price_snap(0.0, 0.0), _PRICE) is None


def test_grid_price_uses_default_margin():
    # No margin in cfg -> default 15%; -20% counts as cheap.
    assert rule_grid_price(_price_snap(0.16, 0.20), {}).key == "grid_price_cheap"


def test_grid_price_margin_configurable():
    cfg = {CONF_PRICE_MARGIN_PCT: 30}
    assert rule_grid_price(_price_snap(0.25, 0.20), cfg) is None  # +25% < 30%


def test_evaluate_rules_includes_grid_price():
    snap = {"net_grid_w": 0.0, "surplus_w": 0.0, "price_now": 0.10, "price_avg": 0.20}
    keys = {a.key for a in evaluate_rules(snap, _PRICE)}
    assert "grid_price_cheap" in keys


# --- laundry / appliance done -----------------------------------------------
def _appliance(name, *, key, awaiting=False, mins=None, running=None):
    return {
        "key": key,
        "name": name,
        "awaiting_unload": awaiting,
        "finished_minutes_ago": mins,
        "running": running,
    }


def test_laundry_done_fires_when_awaiting_unload():
    snap = {
        "appliances": [_appliance("Lavatrice 1", key="dev1", awaiting=True, mins=7)]
    }
    out = rule_laundry_done(snap, {})
    assert len(out) == 1
    c = out[0]
    assert c.key == "laundry_done:dev1"
    assert c.category is Category.CHORES
    assert c.urgency is Urgency.ACT
    assert c.message == (
        "Lavatrice 1 finished 7 minutes ago and the door's still closed — "
        "time to take the laundry out."
    )
    assert c.data == {"appliance": "Lavatrice 1", "finished_minutes_ago": 7}


def test_laundry_done_says_a_moment_ago_when_just_finished():
    snap = {"appliances": [_appliance("Washer", key="d", awaiting=True, mins=0)]}
    assert "finished a moment ago and" in rule_laundry_done(snap, {})[0].message


def test_laundry_done_silent_when_not_awaiting():
    snap = {"appliances": [_appliance("Washer", key="d", awaiting=False, running=True)]}
    assert rule_laundry_done(snap, {}) == []


def test_laundry_done_no_appliances():
    assert rule_laundry_done({}, {}) == []
    assert rule_laundry_done({"appliances": []}, {}) == []


def test_laundry_done_only_for_awaiting_appliance():
    snap = {
        "appliances": [
            _appliance("Washer", key="w", awaiting=True, mins=3),
            _appliance("Dryer", key="d", awaiting=False, running=True),
        ]
    }
    assert [c.key for c in rule_laundry_done(snap, {})] == ["laundry_done:w"]


def test_evaluate_rules_includes_laundry_done():
    snap = {
        "net_grid_w": 0.0,
        "surplus_w": 0.0,
        "appliances": [_appliance("Washer", key="w", awaiting=True, mins=5)],
    }
    keys = {a.key for a in evaluate_rules(snap, {})}
    assert "laundry_done:w" in keys


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
    # At the threshold the reading isn't *above* it, so the wording must not claim so.
    assert "at or above 60%" in out[0].message
    assert "(above 60%)" not in out[0].message


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


# --- outdoor-air gate: temperature band -------------------------------------
def test_co2_suppressed_when_outside_too_cold():
    snap = _co2_snap(("Office", 1500.0), outdoor=2.0)  # below default min 3
    assert rule_co2_ventilate(snap, _CO2) == []


def test_co2_suppressed_when_outside_too_hot():
    snap = _co2_snap(("Office", 1500.0), outdoor=29.0)  # above default max 28
    assert rule_co2_ventilate(snap, _CO2) == []


def test_co2_fires_at_temp_band_edges():
    at_min = rule_co2_ventilate(_co2_snap(("Office", 1500.0), outdoor=3.0), _CO2)
    at_max = rule_co2_ventilate(_co2_snap(("Office", 1500.0), outdoor=28.0), _CO2)
    assert len(at_min) == 1
    assert len(at_max) == 1


def test_co2_temp_band_is_configurable():
    cfg = {
        CONF_CO2_THRESHOLD_PPM: 1000,
        CONF_VENTILATE_MIN_OUTDOOR_TEMP_C: 10,
        CONF_VENTILATE_MAX_OUTDOOR_TEMP_C: 20,
    }
    assert rule_co2_ventilate(_co2_snap(("Office", 1500.0), outdoor=8.0), cfg) == []
    assert rule_co2_ventilate(_co2_snap(("Office", 1500.0), outdoor=25.0), cfg) == []
    within = rule_co2_ventilate(_co2_snap(("Office", 1500.0), outdoor=15.0), cfg)
    assert len(within) == 1


def test_co2_no_temp_gate_when_outdoor_temp_unknown():
    # Outdoor temp missing -> can't judge the band -> stay default-open and fire.
    assert len(rule_co2_ventilate(_co2_snap(("Office", 1500.0)), _CO2)) == 1


# --- outdoor-air gate: moisture import --------------------------------------
def test_co2_suppressed_when_venting_imports_moisture():
    # Indoor 21 C/40% is drier (lower absolute humidity) than outdoor 10 C/95%.
    snap = _co2_snap(
        ("Office", 1500.0),
        outdoor=10.0,
        outdoor_humidity=95.0,
        indoor_temp=21.0,
        indoor_humidity=40.0,
    )
    assert rule_co2_ventilate(snap, _CO2) == []


def test_co2_fires_when_outdoor_air_is_drier():
    snap = _co2_snap(
        ("Office", 1500.0),
        outdoor=10.0,
        outdoor_humidity=30.0,
        indoor_temp=21.0,
        indoor_humidity=40.0,
    )
    out = rule_co2_ventilate(snap, _CO2)
    assert len(out) == 1
    assert out[0].data["outdoor_humidity"] == 30.0


def test_co2_fires_when_absolute_humidity_is_equal():
    # Same temp + RH indoors and out -> equal absolute humidity -> not suppressed.
    snap = _co2_snap(
        ("Office", 1500.0),
        outdoor=18.0,
        outdoor_humidity=50.0,
        indoor_temp=18.0,
        indoor_humidity=50.0,
    )
    assert len(rule_co2_ventilate(snap, _CO2)) == 1


def test_co2_no_moisture_gate_when_indoor_data_missing():
    # Outdoor humidity known but no indoor pair -> moisture check skipped, fires.
    snap = _co2_snap(("Office", 1500.0), outdoor=10.0, outdoor_humidity=95.0)
    assert len(rule_co2_ventilate(snap, _CO2)) == 1


def test_co2_no_moisture_gate_when_outdoor_humidity_missing():
    snap = _co2_snap(
        ("Office", 1500.0), outdoor=10.0, indoor_temp=21.0, indoor_humidity=40.0
    )
    assert len(rule_co2_ventilate(snap, _CO2)) == 1


# --- occupancy gate (opt-in) ------------------------------------------------
def test_co2_occupancy_gate_off_by_default():
    # Default config: an empty room still gets the nudge (gate is opt-in).
    snap = _co2_snap(("Office", 1500.0), occupied=False)
    assert len(rule_co2_ventilate(snap, _CO2)) == 1


def test_co2_suppressed_when_room_empty_and_gate_enabled():
    snap = _co2_snap(("Office", 1500.0), occupied=False)
    assert rule_co2_ventilate(snap, _CO2_OCC) == []


def test_co2_fires_when_room_occupied_and_gate_enabled():
    snap = _co2_snap(("Office", 1500.0), occupied=True)
    assert len(rule_co2_ventilate(snap, _CO2_OCC)) == 1


def test_co2_occupancy_defaults_to_occupied_when_unknown():
    # Gate on but no "occupied" key (e.g. no sensor mapped) -> default occupied.
    snap = {
        "outdoor_temp": None,
        "co2_rooms": [{"entity_id": "sensor.office", "name": "Office", "ppm": 1500.0}],
    }
    assert len(rule_co2_ventilate(snap, _CO2_OCC)) == 1


def test_co2_empty_room_does_not_block_later_occupied_room():
    snap = {
        "outdoor_temp": None,
        "co2_rooms": [
            {
                "entity_id": "sensor.empty",
                "name": "Empty",
                "ppm": 1500.0,
                "occupied": False,
            },
            {
                "entity_id": "sensor.busy",
                "name": "Busy",
                "ppm": 1500.0,
                "occupied": True,
            },
        ],
    }
    assert [c.data["room"] for c in rule_co2_ventilate(snap, _CO2_OCC)] == ["Busy"]


def test_co2_gate_blocked_room_does_not_block_later_room():
    # A room the outdoor-air gate blocks must not stop a later room from firing.
    # Outdoor is muggy (10 C/95%); the first room's drier indoor air gets gated
    # on moisture, the second has no indoor pair so only the (passing) temp band
    # applies and it should still fire.
    snap = {
        "outdoor_temp": 10.0,
        "outdoor_humidity": 95.0,
        "co2_rooms": [
            {
                "entity_id": "sensor.muggy",
                "name": "Muggy",
                "ppm": 1500.0,
                "window_open": False,
                "indoor_temp": 21.0,
                "indoor_humidity": 40.0,
            },
            {
                "entity_id": "sensor.stuffy",
                "name": "Stuffy",
                "ppm": 1500.0,
                "window_open": False,
                "indoor_temp": None,
                "indoor_humidity": None,
            },
        ],
    }
    assert [c.data["room"] for c in rule_co2_ventilate(snap, _CO2)] == ["Stuffy"]


def test_evaluate_rules_collects_single_and_multi():
    snap = {"net_grid_w": -3000.0, "surplus_w": 3000.0, **_rooms(("Bath", 75.0))}
    keys = {a.key for a in evaluate_rules(snap, _CFG)}
    assert keys == {"solar_surplus", "dehumidifier:sensor.bath"}

    none = evaluate_rules({"net_grid_w": 0.0, "surplus_w": 0.0}, _CFG)
    assert none == []
