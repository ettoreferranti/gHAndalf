"""Coordinator that samples the mapped HA entities and derives values.

This is the heart of the "HA-native, source-agnostic" principle: gHAndalf reads
the *live* state machine for whichever entities the user mapped — it never talks
to a vendor API.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BATTERY_SOC,
    CONF_CONSUMPTION_POWER,
    CONF_GRID_EXPORT_POWER,
    CONF_GRID_IMPORT_POWER,
    CONF_PV_POWER,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .helpers import get_conf, net_grid_w, parse_float, solar_surplus_w

_LOGGER = logging.getLogger(__name__)

# Roles read as plain numeric sensors. Maps the result key -> config key.
_NUMERIC_ROLES: dict[str, str] = {
    "pv_w": CONF_PV_POWER,
    "consumption_w": CONF_CONSUMPTION_POWER,
    "grid_import_w": CONF_GRID_IMPORT_POWER,
    "grid_export_w": CONF_GRID_EXPORT_POWER,
    "battery_soc": CONF_BATTERY_SOC,
}


class GHandalfCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads mapped entities on an interval and derives coaching inputs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = int(get_conf(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} snapshot",
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry

    def _read_role(self, config_key: str) -> float | None:
        """Read one mapped entity's current value as a float (or None)."""
        entity_id = get_conf(self.entry, config_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return parse_float(state.state)

    async def _async_update_data(self) -> dict[str, Any]:
        """Sample all mapped entities and compute derived values.

        Never raises ``UpdateFailed`` on a missing sensor — gHAndalf is a coach,
        not a critical service, so it degrades gracefully and reports which
        roles are currently unavailable via the status sensor.
        """
        values: dict[str, Any] = {
            key: self._read_role(conf_key) for key, conf_key in _NUMERIC_ROLES.items()
        }

        values["surplus_w"] = solar_surplus_w(values["pv_w"], values["consumption_w"])
        values["net_grid_w"] = net_grid_w(
            values["grid_import_w"], values["grid_export_w"]
        )

        # Which mapped roles failed to produce a reading this cycle.
        unavailable = [
            conf_key
            for key, conf_key in _NUMERIC_ROLES.items()
            if get_conf(self.entry, conf_key) and values[key] is None
        ]
        values["unavailable_roles"] = unavailable

        return values
