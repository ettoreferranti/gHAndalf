"""The gHAndalf integration — a coach for your home, inside Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import GHandalfCoordinator
from .intent import async_setup_intents

type GHandalfConfigEntry = ConfigEntry[GHandalfCoordinator]

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: GHandalfConfigEntry) -> bool:
    """Set up gHAndalf from a config entry."""
    coordinator = GHandalfCoordinator(hass, entry)
    # Restore persisted cooldown/budget + appliance state before the first poll,
    # so a restart doesn't wipe throttling or forget a load awaiting unload.
    await coordinator.async_load_persisted()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    await async_setup_intents(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GHandalfConfigEntry) -> bool:
    """Unload a config entry."""
    # Flush any pending delayed save before the coordinator goes away, so a
    # reload (e.g. an options change) doesn't lose the latest state.
    await entry.runtime_data.async_save_now()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(
    hass: HomeAssistant, entry: GHandalfConfigEntry
) -> None:
    """Reload the entry when the options flow changes its configuration."""
    await hass.config_entries.async_reload(entry.entry_id)
