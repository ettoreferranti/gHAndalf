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
    CONF_COOLDOWN_MINUTES,
    CONF_DEBOUNCE_SECONDS,
    CONF_DEHUMIDIFIER_POWER_SENSORS,
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_DEHUMIDIFIER_SENSORS,
    CONF_GRID_EXPORT_POWER,
    CONF_GRID_IMPORT_POWER,
    CONF_HUMIDITY_OFF_THRESHOLD_PCT,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_MAX_NUDGES_PER_DAY,
    CONF_PERSONS,
    CONF_PV_POWER,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCAN_INTERVAL,
    CONF_SURPLUS_THRESHOLD_W,
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_DEHUMIDIFIER_RUNNING_WATTS,
    DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT,
    DEFAULT_HUMIDITY_THRESHOLD_PCT,
    DEFAULT_MAX_NUDGES_PER_DAY,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
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
_PERSONS = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="person", multiple=True)
)
_HUMIDITY_SENSORS = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="sensor", device_class="humidity", multiple=True
    )
)
_POWER_SENSORS = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
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
            vol.Optional(CONF_PERSONS): _PERSONS,
            vol.Optional(CONF_DEHUMIDIFIER_SENSORS): _HUMIDITY_SENSORS,
            vol.Optional(CONF_DEHUMIDIFIER_POWER_SENSORS): _POWER_SENSORS,
        }
    )


def _number(min_v: float, max_v: float, step: float, unit: str) -> selector.Selector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_v,
            max=max_v,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _tunables_schema() -> vol.Schema:
    """Numeric / time tunables, only offered in the options flow."""
    return vol.Schema(
        {
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _number(
                MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL, 5, "s"
            ),
            vol.Optional(
                CONF_SURPLUS_THRESHOLD_W, default=DEFAULT_SURPLUS_THRESHOLD_W
            ): _number(0, 20000, 100, "W"),
            vol.Optional(
                CONF_HUMIDITY_THRESHOLD_PCT, default=DEFAULT_HUMIDITY_THRESHOLD_PCT
            ): _number(0, 100, 1, "%"),
            vol.Optional(
                CONF_HUMIDITY_OFF_THRESHOLD_PCT,
                default=DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT,
            ): _number(0, 100, 1, "%"),
            vol.Optional(
                CONF_DEHUMIDIFIER_RUNNING_WATTS,
                default=DEFAULT_DEHUMIDIFIER_RUNNING_WATTS,
            ): _number(0, 5000, 5, "W"),
            vol.Optional(
                CONF_QUIET_START, default=DEFAULT_QUIET_START
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_QUIET_END, default=DEFAULT_QUIET_END
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_DEBOUNCE_SECONDS, default=DEFAULT_DEBOUNCE_SECONDS
            ): _number(0, 3600, 30, "s"),
            vol.Optional(
                CONF_COOLDOWN_MINUTES, default=DEFAULT_COOLDOWN_MINUTES
            ): _number(0, 1440, 5, "min"),
            vol.Optional(
                CONF_MAX_NUDGES_PER_DAY, default=DEFAULT_MAX_NUDGES_PER_DAY
            ): _number(1, 50, 1, ""),
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
