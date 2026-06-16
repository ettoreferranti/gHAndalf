"""Integration tests: set up the entry and verify the derived sensors appear."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
    CONF_CONSUMPTION_POWER,
    CONF_PV_POWER,
    DOMAIN,
)

_POWER_ATTRS = {"device_class": "power", "unit_of_measurement": "W"}


async def test_setup_exposes_sensors_then_unloads(hass: HomeAssistant) -> None:
    """End-to-end: live states -> coordinator -> visible derived sensors."""
    hass.states.async_set("sensor.pv", "3000", _POWER_ATTRS)
    hass.states.async_set("sensor.cons", "1000", _POWER_ATTRS)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_PV_POWER: "sensor.pv", CONF_CONSUMPTION_POWER: "sensor.cons"},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    surplus = hass.states.get("sensor.ghandalf_solar_surplus")
    assert surplus is not None
    assert float(surplus.state) == 2000.0

    status = hass.states.get("sensor.ghandalf_status")
    assert status is not None
    assert status.state == "ok"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
