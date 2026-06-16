"""Config and options flow for gHAndalf.

Everything the component needs is set here through the UI: which entities map to
which roles, and the tunables (scan interval, thresholds). No values live in code.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_BATTERY_SOC,
    CONF_CONSUMPTION_POWER,
    CONF_GRID_EXPORT_POWER,
    CONF_GRID_IMPORT_POWER,
    CONF_PV_POWER,
    CONF_SCAN_INTERVAL,
    CONF_SURPLUS_THRESHOLD_W,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SURPLUS_THRESHOLD_W,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_POWER_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power")
)
_BATTERY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="battery")
)


def _entity_schema() -> vol.Schema:
    """The entity-role mapping (shared by config and options flows)."""
    return vol.Schema(
        {
            vol.Required(CONF_PV_POWER): _POWER_SENSOR,
            vol.Required(CONF_CONSUMPTION_POWER): _POWER_SENSOR,
            vol.Optional(CONF_GRID_IMPORT_POWER): _POWER_SENSOR,
            vol.Optional(CONF_GRID_EXPORT_POWER): _POWER_SENSOR,
            vol.Optional(CONF_BATTERY_SOC): _BATTERY_SENSOR,
        }
    )


def _tunables_schema() -> vol.Schema:
    """Numeric tunables, only offered in the options flow."""
    return vol.Schema(
        {
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Optional(
                CONF_SURPLUS_THRESHOLD_W, default=DEFAULT_SURPLUS_THRESHOLD_W
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=20000,
                    step=100,
                    unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


class GHandalfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: map the core energy entities."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-instance setup, mapping the required energy entities."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="gHAndalf", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_entity_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return GHandalfOptionsFlow()


class GHandalfOptionsFlow(OptionsFlow):
    """Re-map entities and retune values without re-adding the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the full editable config, pre-filled with current values."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = _entity_schema().extend(_tunables_schema().schema)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
        )
