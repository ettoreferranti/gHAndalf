"""Tests for the coordinator's reading and degraded-state reporting."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
    CONF_BATTERY_SOC,
    CONF_CONSUMPTION_POWER,
    CONF_GRID_EXPORT_POWER,
    CONF_GRID_IMPORT_POWER,
    CONF_PV_POWER,
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
