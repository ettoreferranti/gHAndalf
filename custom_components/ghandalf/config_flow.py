"""Config and options flow for gHAndalf.

Both flows are generic: they assemble their forms from the declarative sections
in ``config_schema``. Initial setup asks only for the essentials; everything else
is grouped into a menu under Configure, with per-field help text. Adding a rule
means adding its fields to a section — never touching this file.
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

from .config_schema import (
    MENU_OPTIONS,
    SECTION_BY_ID,
    Section,
    section_keys,
    section_schema,
    setup_schema,
)
from .const import DOMAIN


class GHandalfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: map just the essential energy entities."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="gHAndalf", data=user_input)

        return self.async_show_form(step_id="user", data_schema=setup_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GHandalfOptionsFlow()


class GHandalfOptionsFlow(OptionsFlow):
    """Grouped settings: a menu of domain sections, each its own focused form."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=MENU_OPTIONS)

    # One thin handler per section (HA routes options steps by method name).
    async def async_step_energy(self, user_input=None) -> ConfigFlowResult:
        return await self._edit(SECTION_BY_ID["energy"], user_input)

    async def async_step_air_quality(self, user_input=None) -> ConfigFlowResult:
        return await self._edit(SECTION_BY_ID["air_quality"], user_input)

    async def async_step_presence(self, user_input=None) -> ConfigFlowResult:
        return await self._edit(SECTION_BY_ID["presence"], user_input)

    async def async_step_advanced(self, user_input=None) -> ConfigFlowResult:
        return await self._edit(SECTION_BY_ID["advanced"], user_input)

    async def _edit(
        self, section: Section, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Render a section's form (pre-filled), or save its submitted values."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            # Replace exactly this section's keys (so cleared optionals are dropped),
            # preserving every other section's values.
            merged = {
                k: v for k, v in current.items() if k not in section_keys(section)
            }
            merged.update(user_input)
            return self.async_create_entry(title="", data=merged)

        schema = self.add_suggested_values_to_schema(section_schema(section), current)
        return self.async_show_form(step_id=section.step_id, data_schema=schema)
