"""Tests for the gHAndalf config and options flows (menu + sections)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghandalf.const import (
    CONF_CONSUMPTION_POWER,
    CONF_DEHUMIDIFIER_SENSORS,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_MAX_NUDGES_PER_DAY,
    CONF_PV_POWER,
    CONF_SURPLUS_THRESHOLD_W,
    DOMAIN,
)

_ESSENTIALS = {CONF_PV_POWER: "sensor.pv", CONF_CONSUMPTION_POWER: "sensor.cons"}


async def test_user_flow_asks_only_essentials(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # Only the two essentials are asked for at setup.
    assert set(result["data_schema"].schema) == {CONF_PV_POWER, CONF_CONSUMPTION_POWER}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(_ESSENTIALS)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "gHAndalf"
    assert result["data"][CONF_PV_POWER] == "sensor.pv"


async def test_single_instance_only(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_menu_lists_sections(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=dict(_ESSENTIALS))
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "energy",
        "air_quality",
        "appliances",
        "presence",
        "notifications",
        "advanced",
    }


async def test_options_edit_section_preserves_other_sections(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data=dict(_ESSENTIALS),
        options={CONF_DEHUMIDIFIER_SENSORS: ["sensor.bath"]},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "energy"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "energy"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**_ESSENTIALS, CONF_SURPLUS_THRESHOLD_W: 1500}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SURPLUS_THRESHOLD_W] == 1500
    # The air-quality section's value is untouched.
    assert result["data"][CONF_DEHUMIDIFIER_SENSORS] == ["sensor.bath"]


async def test_options_clears_omitted_optional(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data=dict(_ESSENTIALS),
        options={
            CONF_DEHUMIDIFIER_SENSORS: ["sensor.bath"],
            CONF_HUMIDITY_THRESHOLD_PCT: 55,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "air_quality"}
    )
    # Submit the section without the dehumidifier sensors -> they're dropped.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HUMIDITY_THRESHOLD_PCT: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DEHUMIDIFIER_SENSORS not in result["data"]
    assert result["data"][CONF_HUMIDITY_THRESHOLD_PCT] == 60


async def test_options_advanced_and_presence_steps(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=dict(_ESSENTIALS))
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    assert result["step_id"] == "advanced"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_NUDGES_PER_DAY: 5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAX_NUDGES_PER_DAY] == 5

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "presence"}
    )
    assert result["step_id"] == "presence"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
