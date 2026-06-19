"""Tests for the Assist appliance-status intent."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent as ha_intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
    CONF_APPLIANCE_PROGRESS_SENSORS,
    CONF_CONSUMPTION_POWER,
    CONF_PV_POWER,
    DOMAIN,
)
from custom_components.ghandalf.intent import INTENT_LAUNDRY_STATUS, _appliance_phrase


def test_phrase_running_with_minutes():
    p = _appliance_phrase({"name": "Washer", "running": True, "minutes_left": 5})
    assert p == "Washer has about 5 minutes left"


def test_phrase_running_without_minutes():
    p = _appliance_phrase({"name": "Washer", "running": True, "minutes_left": None})
    assert p == "Washer is running"


def test_phrase_awaiting_unload():
    p = _appliance_phrase(
        {"name": "Washer", "awaiting_unload": True, "finished_minutes_ago": 7}
    )
    assert p.startswith("Washer finished 7 minutes ago")
    assert "take the laundry out" in p


def test_phrase_off():
    assert _appliance_phrase({"name": "Dryer"}) == "Dryer is off"


async def test_intent_handler_reports_status(hass: HomeAssistant) -> None:
    """The registered intent speaks the tracked appliances' status."""
    hass.states.async_set("sensor.pv", "0", {"device_class": "power"})
    hass.states.async_set("sensor.cons", "0", {"device_class": "power"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv",
            CONF_CONSUMPTION_POWER: "sensor.cons",
            CONF_APPLIANCE_PROGRESS_SENSORS: ["sensor.washer_time"],
        },
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "washer")},
        name="Lavatrice 1",
    )
    t = er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "wtime",
        suggested_object_id="washer_time",
        device_id=device.id,
    )
    hass.states.async_set(
        t.entity_id, "8", {"device_class": "duration", "unit_of_measurement": "min"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    response = await ha_intent.async_handle(hass, DOMAIN, INTENT_LAUNDRY_STATUS, {})
    speech = response.speech["plain"]["speech"]
    assert "minutes left" in speech


async def test_intent_handler_no_appliances(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.pv", "0", {"device_class": "power"})
    hass.states.async_set("sensor.cons", "0", {"device_class": "power"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_PV_POWER: "sensor.pv", CONF_CONSUMPTION_POWER: "sensor.cons"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    response = await ha_intent.async_handle(hass, DOMAIN, INTENT_LAUNDRY_STATUS, {})
    assert "No appliances" in response.speech["plain"]["speech"]
