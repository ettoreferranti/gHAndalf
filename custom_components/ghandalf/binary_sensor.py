"""Binary sensors: simple on/off signals for automations and HomeKit/Siri.

``laundry_ready`` turns on when any tracked appliance has finished a cycle and
hasn't been unloaded yet. Exposed to HA's HomeKit bridge it maps to a contact
sensor, so you can ask Siri or build Home-app automations off it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GHandalfConfigEntry
from .const import DOMAIN
from .coordinator import GHandalfCoordinator


@dataclass(frozen=True, kw_only=True)
class GHandalfBinarySensorDescription(BinarySensorEntityDescription):
    """A gHAndalf binary sensor plus how to derive its on/off state."""

    is_on_fn: Callable[[dict[str, Any]], bool]


def _laundry_ready(data: dict[str, Any]) -> bool:
    return any(a.get("awaiting_unload") for a in data.get("appliances", []))


BINARY_SENSORS: tuple[GHandalfBinarySensorDescription, ...] = (
    GHandalfBinarySensorDescription(
        key="laundry_ready",
        translation_key="laundry_ready",
        is_on_fn=_laundry_ready,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GHandalfConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up gHAndalf binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GHandalfBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class GHandalfBinarySensor(CoordinatorEntity[GHandalfCoordinator], BinarySensorEntity):
    """A derived on/off signal backed by the coordinator snapshot."""

    _attr_has_entity_name = True
    entity_description: GHandalfBinarySensorDescription

    def __init__(
        self,
        coordinator: GHandalfCoordinator,
        entry: GHandalfConfigEntry,
        description: GHandalfBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="gHAndalf",
            manufacturer="gHAndalf",
            model="Home coach",
        )

    @property
    def is_on(self) -> bool:
        """Whether the signal is currently active."""
        return self.entity_description.is_on_fn(self.coordinator.data)
