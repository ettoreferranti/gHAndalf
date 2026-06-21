"""Tests for the coordinator's reading and degraded-state reporting."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.ghandalf.const import (
    CONF_APPLIANCE_DOOR_SENSORS,
    CONF_APPLIANCE_PROGRESS_SENSORS,
    CONF_BATTERY_SOC,
    CONF_CO2_SENSORS,
    CONF_CONSUMPTION_POWER,
    CONF_DEBOUNCE_SECONDS,
    CONF_DEHUMIDIFIER_POWER_SENSORS,
    CONF_DEHUMIDIFIER_SENSORS,
    CONF_GRID_EXPORT_POWER,
    CONF_GRID_IMPORT_POWER,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_INDOOR_HUMIDITY_SENSORS,
    CONF_INDOOR_TEMP_SENSORS,
    CONF_NOTIFY_PERSISTENT,
    CONF_NOTIFY_TARGETS,
    CONF_OCCUPANCY_SENSORS,
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMP_SENSORS,
    CONF_PERSONS,
    CONF_PRICE_AVERAGE_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PV_POWER,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REQUIRE_OCCUPANCY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)
from custom_components.ghandalf.coordinator import (
    _deserialize_appliance_state,
    _serialize_appliance_state,
)

_POWER_ATTRS = {"device_class": "power", "unit_of_measurement": "W"}


async def test_derived_values_and_degraded_status(hass: HomeAssistant) -> None:
    """Net grid + surplus are derived; a mapped-but-missing role is degraded."""
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.imp", "0", _POWER_ATTRS)
    hass.states.async_set("sensor.exp", "2000", _POWER_ATTRS)
    # battery_soc is mapped to an entity that does not exist -> degraded

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_GRID_IMPORT_POWER: "sensor.imp",
            CONF_GRID_EXPORT_POWER: "sensor.exp",
            CONF_BATTERY_SOC: "sensor.does_not_exist",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    data = entry.runtime_data.data
    assert data["surplus_w"] == 2000.0
    assert data["net_grid_w"] == -2000.0
    assert data["unavailable_roles"] == [CONF_BATTERY_SOC]

    net = hass.states.get("sensor.ghandalf_net_grid_power")
    assert net is not None
    assert float(net.state) == -2000.0

    status = hass.states.get("sensor.ghandalf_status")
    assert status is not None
    assert status.state == "degraded"
    assert status.attributes["unavailable_roles"] == [CONF_BATTERY_SOC]

    # Exporting 2000 W > default 1000 W threshold -> a surplus advice candidate.
    assert [a["key"] for a in data["advice"]] == ["solar_surplus"]

    advice = hass.states.get("sensor.ghandalf_active_advice")
    assert advice is not None
    assert advice.state == "1"
    assert advice.attributes["presence_home"] is True
    assert "grid" in advice.attributes["summary"]


async def test_presence_gates_nudges(hass: HomeAssistant) -> None:
    """Rules still detect when away, but the gate withholds the nudge."""
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)
    hass.states.async_set("person.someone", "not_home")

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_PERSONS: ["person.someone"],
            # Make gating deterministic regardless of wall-clock time.
            CONF_DEBOUNCE_SECONDS: 0,
            CONF_QUIET_START: "00:00:00",
            CONF_QUIET_END: "00:00:00",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    data = entry.runtime_data.data
    assert data["presence_home"] is False
    assert [a["key"] for a in data["advice"]] == ["solar_surplus"]  # detected
    assert data["pending_nudges"] == []  # but withheld — nobody home

    # Someone comes home -> the nudge is now allowed through.
    hass.states.async_set("person.someone", "home")
    await entry.runtime_data.async_refresh()
    data = entry.runtime_data.data
    assert data["presence_home"] is True
    assert data["pending_nudges"] == ["solar_surplus"]


async def test_dehumidifier_advice_with_room_name(hass: HomeAssistant) -> None:
    """A mapped humid room produces dehumidifier advice; name falls back to friendly."""
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)  # no surplus
    hass.states.async_set(
        "sensor.bath_hum",
        "72",
        {
            "device_class": "humidity",
            "unit_of_measurement": "%",
            "friendly_name": "Bathroom Humidity",
        },
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_DEHUMIDIFIER_SENSORS: ["sensor.bath_hum"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    advice = entry.runtime_data.data["advice"]
    match = [a for a in advice if a["key"] == "dehumidifier:sensor.bath_hum"]
    assert len(match) == 1
    assert "Bathroom Humidity" in match[0]["message"]
    assert "72%" in match[0]["message"]


async def test_dehumidifier_room_name_follows_ha_area(hass: HomeAssistant) -> None:
    """A sensor's HA area names the room, even if its friendly name is stale.

    Mirrors the real case: an Aqara moved to the basement still reads
    "Office Elisa ..." as its friendly name, but its area is set to Basement.
    """
    area = ar.async_get(hass).async_get_or_create("Basement")
    reg = er.async_get(hass).async_get_or_create(
        "sensor", "ghandalf_test", "moved-aqara", suggested_object_id="moved_aqara"
    )
    er.async_get(hass).async_update_entity(reg.entity_id, area_id=area.id)
    hass.states.async_set(
        reg.entity_id,
        "68",
        {"device_class": "humidity", "friendly_name": "Office Elisa Humidity"},
    )
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_DEHUMIDIFIER_SENSORS: [reg.entity_id],
            CONF_HUMIDITY_THRESHOLD_PCT: 65,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    advice = entry.runtime_data.data["advice"]
    match = [a for a in advice if a["key"].startswith("dehumidifier:")]
    assert len(match) == 1
    assert "Basement" in match[0]["message"]  # area wins
    assert "Office Elisa" not in match[0]["message"]  # not the stale friendly name


async def test_dehumidifier_suppressed_when_plug_running(hass: HomeAssistant) -> None:
    """A powered plug in the humidity sensor's area suppresses that room's advice."""
    area = ar.async_get(hass).async_get_or_create("Basement")
    reg = er.async_get(hass)
    hum = reg.async_get_or_create(
        "sensor", "ghandalf_test", "h", suggested_object_id="b_hum"
    )
    pwr = reg.async_get_or_create(
        "sensor", "ghandalf_test", "p", suggested_object_id="b_plug"
    )
    reg.async_update_entity(hum.entity_id, area_id=area.id)
    reg.async_update_entity(pwr.entity_id, area_id=area.id)
    hass.states.async_set(hum.entity_id, "70", {"device_class": "humidity"})
    hass.states.async_set(pwr.entity_id, "250", {"device_class": "power"})
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_DEHUMIDIFIER_SENSORS: [hum.entity_id],
            CONF_DEHUMIDIFIER_POWER_SENSORS: [pwr.entity_id],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    data = entry.runtime_data.data
    # The plug power was paired to the room by shared area...
    assert data["dehumidifier_rooms"][0]["power_w"] == 250.0
    # ...and because it's running, no advice is produced.
    assert not any(a["key"].startswith("dehumidifier:") for a in data["advice"])


async def test_dehumidifier_off_advice_when_dry_and_running(
    hass: HomeAssistant,
) -> None:
    """A dry room whose plug is running gets a 'switch it off' nudge."""
    area = ar.async_get(hass).async_get_or_create("Basement")
    reg = er.async_get(hass)
    hum = reg.async_get_or_create(
        "sensor", "ghandalf_test", "ho", suggested_object_id="b_hum_off"
    )
    pwr = reg.async_get_or_create(
        "sensor", "ghandalf_test", "po", suggested_object_id="b_plug_off"
    )
    reg.async_update_entity(hum.entity_id, area_id=area.id)
    reg.async_update_entity(pwr.entity_id, area_id=area.id)
    hass.states.async_set(hum.entity_id, "40", {"device_class": "humidity"})
    hass.states.async_set(pwr.entity_id, "250", {"device_class": "power"})
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_DEHUMIDIFIER_SENSORS: [hum.entity_id],
            CONF_DEHUMIDIFIER_POWER_SENSORS: [pwr.entity_id],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    advice = entry.runtime_data.data["advice"]
    off = [a for a in advice if a["key"].startswith("dehumidifier_off:")]
    assert len(off) == 1
    assert "switch the dehumidifier off" in off[0]["message"]


async def test_co2_advice_with_outdoor_and_window_suppression(
    hass: HomeAssistant,
) -> None:
    """High CO2 with a closed window advises (with outdoor temp); open suppresses."""
    area = ar.async_get(hass).async_get_or_create("Office")
    reg = er.async_get(hass)
    co2 = reg.async_get_or_create(
        "sensor", "ghandalf_test", "co2", suggested_object_id="office_co2"
    )
    win = reg.async_get_or_create(
        "binary_sensor", "ghandalf_test", "win", suggested_object_id="office_window"
    )
    reg.async_update_entity(co2.entity_id, area_id=area.id)
    reg.async_update_entity(win.entity_id, area_id=area.id)
    hass.states.async_set(co2.entity_id, "1300", {"device_class": "carbon_dioxide"})
    hass.states.async_set(win.entity_id, "off", {"device_class": "window"})  # closed
    hass.states.async_set("sensor.outdoor", "18", {"device_class": "temperature"})
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_CO2_SENSORS: [co2.entity_id],
            CONF_WINDOW_SENSORS: [win.entity_id],
            CONF_OUTDOOR_TEMP_SENSORS: ["sensor.outdoor"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    advice = entry.runtime_data.data["advice"]
    co2_adv = [a for a in advice if a["key"].startswith("co2:")]
    assert len(co2_adv) == 1
    assert "Office" in co2_adv[0]["message"]
    assert "18°" in co2_adv[0]["message"]

    # Open the window -> same area -> advice suppressed.
    hass.states.async_set(win.entity_id, "on", {"device_class": "window"})
    await entry.runtime_data.async_refresh()
    advice = entry.runtime_data.data["advice"]
    assert not any(a["key"].startswith("co2:") for a in advice)


async def test_outdoor_temp_uses_priority_fallback(hass: HomeAssistant) -> None:
    """First entity with a reading wins; an unavailable primary falls through."""
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)
    hass.states.async_set(
        "sensor.local_temp", "unavailable", {"device_class": "temperature"}
    )
    hass.states.async_set("sensor.weather_temp", "12", {"device_class": "temperature"})

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_OUTDOOR_TEMP_SENSORS: ["sensor.local_temp", "sensor.weather_temp"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Primary unavailable -> fell through to the weather fallback.
    assert entry.runtime_data.data["outdoor_temp"] == 12.0


async def test_co2_advice_suppressed_when_venting_would_import_moisture(
    hass: HomeAssistant,
) -> None:
    """Indoor/outdoor humidity (paired by area) gates the nudge; drier air re-fires."""
    area = ar.async_get(hass).async_get_or_create("Office")
    reg = er.async_get(hass)
    co2 = reg.async_get_or_create(
        "sensor", "ghandalf_test", "co2", suggested_object_id="office_co2"
    )
    in_t = reg.async_get_or_create(
        "sensor", "ghandalf_test", "in_t", suggested_object_id="office_temp"
    )
    in_h = reg.async_get_or_create(
        "sensor", "ghandalf_test", "in_h", suggested_object_id="office_humidity"
    )
    for ent in (co2, in_t, in_h):
        reg.async_update_entity(ent.entity_id, area_id=area.id)
    hass.states.async_set(co2.entity_id, "1300", {"device_class": "carbon_dioxide"})
    hass.states.async_set(in_t.entity_id, "21", {"device_class": "temperature"})
    hass.states.async_set(in_h.entity_id, "40", {"device_class": "humidity"})
    # Outdoor 10 °C is inside the temp band, so only the moisture gate is in play.
    hass.states.async_set("sensor.out_t", "10", {"device_class": "temperature"})
    hass.states.async_set("sensor.out_h", "95", {"device_class": "humidity"})  # muggy
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_CO2_SENSORS: [co2.entity_id],
            CONF_OUTDOOR_TEMP_SENSORS: ["sensor.out_t"],
            CONF_OUTDOOR_HUMIDITY_SENSORS: ["sensor.out_h"],
            CONF_INDOOR_TEMP_SENSORS: [in_t.entity_id],
            CONF_INDOOR_HUMIDITY_SENSORS: [in_h.entity_id],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Muggy outside (more absolute moisture than the room) -> suppressed.
    advice = entry.runtime_data.data["advice"]
    assert not any(a["key"].startswith("co2:") for a in advice)

    # Dry the outdoor air -> airing out now helps -> advice fires.
    hass.states.async_set("sensor.out_h", "30", {"device_class": "humidity"})
    await entry.runtime_data.async_refresh()
    advice = entry.runtime_data.data["advice"]
    assert any(a["key"].startswith("co2:") for a in advice)


async def test_co2_advice_suppressed_when_room_unoccupied(hass: HomeAssistant) -> None:
    """With the gate on, an empty room (motion past grace) is skipped; walk-in fires."""
    area = ar.async_get(hass).async_get_or_create("Office")
    reg = er.async_get(hass)
    co2 = reg.async_get_or_create(
        "sensor", "ghandalf_test", "co2", suggested_object_id="office_co2"
    )
    occ = reg.async_get_or_create(
        "binary_sensor", "ghandalf_test", "occ", suggested_object_id="office_motion"
    )
    reg.async_update_entity(co2.entity_id, area_id=area.id)
    reg.async_update_entity(occ.entity_id, area_id=area.id)
    hass.states.async_set(co2.entity_id, "1300", {"device_class": "carbon_dioxide"})
    # Motion last cleared 30 min ago -> beyond the 15-min grace -> room is empty.
    with freeze_time(dt_util.utcnow() - timedelta(minutes=30)):
        hass.states.async_set(occ.entity_id, "off", {"device_class": "occupancy"})
    hass.states.async_set("sensor.pv", "1000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_CO2_SENSORS: [co2.entity_id],
            CONF_OCCUPANCY_SENSORS: [occ.entity_id],
            CONF_REQUIRE_OCCUPANCY: True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    advice = entry.runtime_data.data["advice"]
    assert not any(a["key"].startswith("co2:") for a in advice)

    # Someone walks in -> motion on -> advice fires.
    hass.states.async_set(occ.entity_id, "on", {"device_class": "occupancy"})
    await entry.runtime_data.async_refresh()
    advice = entry.runtime_data.data["advice"]
    assert any(a["key"].startswith("co2:") for a in advice)


async def test_grid_price_advice_fires_and_stays_silent_when_flat(
    hass: HomeAssistant,
) -> None:
    """A cheap price (vs the day's average) advises; a flat price stays silent."""
    _PRICE_ATTRS = {"unit_of_measurement": "CHF/kWh"}
    hass.states.async_set("sensor.pv", "0", _POWER_ATTRS)  # no solar surplus
    hass.states.async_set("sensor.cons", "0", _POWER_ATTRS)
    hass.states.async_set("sensor.price", "0.10", _PRICE_ATTRS)
    hass.states.async_set("sensor.price_avg", "0.20", _PRICE_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_PRICE_SENSOR: "sensor.price",
            CONF_PRICE_AVERAGE_SENSOR: "sensor.price_avg",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    keys = [a["key"] for a in entry.runtime_data.data["advice"]]
    assert "grid_price_cheap" in keys

    # Price equals the average (flat tariff, like 400F today) -> no price advice.
    hass.states.async_set("sensor.price", "0.20", _PRICE_ATTRS)
    await entry.runtime_data.async_refresh()
    keys = [a["key"] for a in entry.runtime_data.data["advice"]]
    assert not any(k.startswith("grid_price_") for k in keys)


async def test_appliance_laundry_lifecycle(hass: HomeAssistant) -> None:
    """Run -> finish -> held-while-offline -> door opens, end to end via the device."""
    hass.states.async_set("sensor.pv", "0", _POWER_ATTRS)  # no solar surplus
    hass.states.async_set("sensor.cons", "0", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_APPLIANCE_PROGRESS_SENSORS: ["sensor.washer_time"],
            CONF_APPLIANCE_DOOR_SENSORS: ["binary_sensor.washer_door"],
            CONF_DEBOUNCE_SECONDS: 0,
            CONF_QUIET_START: "00:00:00",
            CONF_QUIET_END: "00:00:00",
        },
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "washer")},
        name="Lavatrice 1",
    )
    reg = er.async_get(hass)
    t = reg.async_get_or_create(
        "sensor",
        "test",
        "wtime",
        suggested_object_id="washer_time",
        device_id=device.id,
    )
    d = reg.async_get_or_create(
        "binary_sensor",
        "test",
        "wdoor",
        suggested_object_id="washer_door",
        device_id=device.id,
    )
    _DUR = {"device_class": "duration", "unit_of_measurement": "min"}
    hass.states.async_set(t.entity_id, "5", _DUR)  # 5 min left, running
    hass.states.async_set(d.entity_id, "off", {"device_class": "door"})  # closed

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    app = entry.runtime_data.data["appliances"][0]
    assert app["name"] == "Lavatrice 1"
    assert app["running"] is True and app["minutes_left"] == 5
    assert app["awaiting_unload"] is False
    assert hass.states.get("binary_sensor.ghandalf_laundry_ready").state == "off"

    # Cycle finishes (time-to-end -> 0) -> awaiting unload + advice + binary on.
    hass.states.async_set(t.entity_id, "0", _DUR)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data["appliances"][0]["awaiting_unload"] is True
    advice = entry.runtime_data.data["advice"]
    assert any(a["key"] == f"laundry_done:{device.id}" for a in advice)
    assert hass.states.get("binary_sensor.ghandalf_laundry_ready").state == "on"

    # Machine goes offline (sensor unavailable) -> awaiting is HELD.
    hass.states.async_set(t.entity_id, "unavailable", _DUR)
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["appliances"][0]["awaiting_unload"] is True

    # Door opens -> unloaded -> cleared, advice gone, binary off.
    hass.states.async_set(d.entity_id, "on", {"device_class": "door"})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data["appliances"][0]["awaiting_unload"] is False
    advice = entry.runtime_data.data["advice"]
    assert not any(a["key"].startswith("laundry_done:") for a in advice)
    assert hass.states.get("binary_sensor.ghandalf_laundry_ready").state == "off"


def _nudge_entry(**extra) -> MockConfigEntry:
    """A config entry whose solar-surplus nudge fires deterministically."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_DEBOUNCE_SECONDS: 0,
            CONF_QUIET_START: "00:00:00",
            CONF_QUIET_END: "00:00:00",
            **extra,
        },
    )


async def test_notification_pushed_when_nudge_fires(hass: HomeAssistant) -> None:
    """A fired nudge is pushed to each configured notify target, once."""
    calls = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = _nudge_entry(**{CONF_NOTIFY_TARGETS: ["notify.phone"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.data["pending_nudges"] == ["solar_surplus"]
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["notify.phone"]
    assert calls[0].data["title"] == "🧙 gHAndalf"
    assert calls[0].data["message"].startswith("You're sending about 2000 W")

    # Still cooling down on the next cycle -> no duplicate push.
    await entry.runtime_data.async_refresh()
    assert len(calls) == 1


async def test_no_notification_without_a_target(hass: HomeAssistant) -> None:
    """The nudge still fires on the sensor, but nothing is pushed."""
    calls = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = _nudge_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.data["pending_nudges"] == ["solar_surplus"]
    assert calls == []


async def test_persistent_notification_when_panel_enabled(hass: HomeAssistant) -> None:
    """The panel toggle posts to persistent_notification, keyed per advice."""
    notify_calls = async_mock_service(hass, "notify", "send_message")
    panel_calls = async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    # Panel on, no phone target -> web-only.
    entry = _nudge_entry(**{CONF_NOTIFY_PERSISTENT: True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.data["pending_nudges"] == ["solar_surplus"]
    assert notify_calls == []  # no phone target mapped
    assert len(panel_calls) == 1
    assert panel_calls[0].data["notification_id"] == "ghandalf_solar_surplus"
    assert panel_calls[0].data["title"] == "🧙 gHAndalf"
    assert panel_calls[0].data["message"].startswith("You're sending about 2000 W")


async def test_both_channels_when_target_and_panel_enabled(
    hass: HomeAssistant,
) -> None:
    """A phone target and the panel toggle each get the nudge."""
    notify_calls = async_mock_service(hass, "notify", "send_message")
    panel_calls = async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = _nudge_entry(
        **{CONF_NOTIFY_TARGETS: ["notify.phone"], CONF_NOTIFY_PERSISTENT: True}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(notify_calls) == 1
    assert len(panel_calls) == 1


async def test_slow_notifier_does_not_stall_updates(hass: HomeAssistant) -> None:
    """A hung notify service must not freeze the coordinator's update loop."""
    release = asyncio.Event()

    async def _hang(call):
        await release.wait()  # never returns until we let it

    hass.services.async_register("notify", "send_message", _hang)
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = _nudge_entry(**{CONF_NOTIFY_TARGETS: ["notify.phone"]})
    entry.add_to_hass(hass)
    # Setup fires the nudge and dispatches the (hanging) notify, but must return.
    assert await hass.config_entries.async_setup(entry.entry_id)

    assert entry.runtime_data.last_update_success
    assert entry.runtime_data.data["pending_nudges"] == ["solar_surplus"]

    # A subsequent refresh also completes, despite the notifier still hanging.
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success

    release.set()  # let the background notify task finish so teardown is clean
    await hass.async_block_till_done()


def test_appliance_state_round_trips() -> None:
    """Serialize -> deserialize restores the cycle state, datetimes and all."""
    finished = datetime(2026, 6, 19, 14, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    state = {
        "dev1": {
            "was_running": False,
            "awaiting_unload": True,
            "finished_at": finished,
        },
        "dev2": {"was_running": True, "awaiting_unload": False, "finished_at": None},
    }
    restored = _deserialize_appliance_state(_serialize_appliance_state(state))
    assert restored == state


def test_deserialize_appliance_state_skips_garbage() -> None:
    """A corrupt store entry is dropped rather than crashing setup."""
    restored = _deserialize_appliance_state(
        {
            "ok": {"awaiting_unload": True, "finished_at": "not-a-date"},
            "bad": "not-a-dict",
        }
    )
    # "bad" dropped; "ok" kept with the unparseable datetime nulled out.
    assert restored == {
        "ok": {"was_running": False, "awaiting_unload": True, "finished_at": None}
    }


async def test_appliance_awaiting_unload_survives_reload(hass: HomeAssistant) -> None:
    """A load that finished before a reload is still remembered afterwards.

    Without persistence, the fresh coordinator would never have seen the
    running->finished transition (the machine is offline on boot) and would
    forget the waiting laundry — exactly the restart wrinkle this slice fixes.
    """
    hass.states.async_set("sensor.pv", "0", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "0", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_APPLIANCE_PROGRESS_SENSORS: ["sensor.washer_time"],
            CONF_APPLIANCE_DOOR_SENSORS: ["binary_sensor.washer_door"],
            CONF_DEBOUNCE_SECONDS: 0,
            CONF_QUIET_START: "00:00:00",
            CONF_QUIET_END: "00:00:00",
        },
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "washer")},
        name="Lavatrice 1",
    )
    reg = er.async_get(hass)
    t = reg.async_get_or_create(
        "sensor",
        "test",
        "wtime",
        suggested_object_id="washer_time",
        device_id=device.id,
    )
    d = reg.async_get_or_create(
        "binary_sensor",
        "test",
        "wdoor",
        suggested_object_id="washer_door",
        device_id=device.id,
    )
    _DUR = {"device_class": "duration", "unit_of_measurement": "min"}
    hass.states.async_set(t.entity_id, "5", _DUR)  # running
    hass.states.async_set(d.entity_id, "off", {"device_class": "door"})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Cycle finishes -> awaiting unload, then the smart appliance drops offline.
    hass.states.async_set(t.entity_id, "0", _DUR)
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["appliances"][0]["awaiting_unload"] is True
    hass.states.async_set(t.entity_id, "unavailable", _DUR)
    await entry.runtime_data.async_refresh()

    # Reload (unload flushes the store; setup rehydrates it). The sensor is still
    # offline, so the only way to know laundry waits is the persisted state.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.data["appliances"][0]["awaiting_unload"] is True
    advice = entry.runtime_data.data["advice"]
    assert any(a["key"] == f"laundry_done:{device.id}" for a in advice)


async def test_nudge_cooldown_survives_reload(hass: HomeAssistant) -> None:
    """A nudge on cooldown stays quiet after a reload (no re-push on restart)."""
    calls = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = _nudge_entry(**{CONF_NOTIFY_TARGETS: ["notify.phone"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls) == 1  # fired once, now on cooldown

    # Reload: the still-true surplus condition must not re-push — cooldown persisted.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data["advice"][0]["key"] == "solar_surplus"  # still seen
    assert len(calls) == 1  # but no duplicate push
