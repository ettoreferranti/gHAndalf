"""Tests for the gHAndalf config and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
    CONF_CONSUMPTION_POWER,
    CONF_PV_POWER,
    CONF_SCAN_INTERVAL,
    CONF_SURPLUS_THRESHOLD_W,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The happy path maps the required entities and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PV_POWER: "sensor.pv_power",
            CONF_CONSUMPTION_POWER: "sensor.consumption",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "gHAndalf"
    assert result["data"][CONF_PV_POWER] == "sensor.pv_power"
    assert result["data"][CONF_CONSUMPTION_POWER] == "sensor.consumption"


async def test_single_instance_only(hass: HomeAssistant) -> None:
    """A second setup attempt aborts — gHAndalf is single-instance."""
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_retunes(hass: HomeAssistant) -> None:
    """The options flow re-maps entities and stores tunables in options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_PV_POWER: "sensor.pv_power",
            CONF_CONSUMPTION_POWER: "sensor.consumption",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PV_POWER: "sensor.pv_power",
            CONF_CONSUMPTION_POWER: "sensor.consumption",
            CONF_SCAN_INTERVAL: 60,
            CONF_SURPLUS_THRESHOLD_W: 1500,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 60
    assert result["data"][CONF_SURPLUS_THRESHOLD_W] == 1500
