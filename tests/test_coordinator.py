"""Tests for the coordinator's reading and degraded-state reporting."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
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
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMP_SENSORS,
    CONF_PERSONS,
    CONF_PV_POWER,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_WINDOW_SENSORS,
    DOMAIN,
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
