"""Diagnostic / derived sensors so gHAndalf's reading of live state is visible.

These are intentionally minimal for the scaffolding slice: they prove the
config -> coordinator -> live-read pipeline end to end. The coaching nudges and
digest come in later slices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GHandalfConfigEntry
from .const import DOMAIN
from .coordinator import GHandalfCoordinator


@dataclass(frozen=True, kw_only=True)
class GHandalfSensorDescription(SensorEntityDescription):
    """Describes a gHAndalf sensor, including how to derive its value."""

    value_fn: Callable[[dict[str, Any]], StateType]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _status(data: dict[str, Any]) -> str:
    return "degraded" if data.get("unavailable_roles") else "ok"


def _status_attrs(data: dict[str, Any]) -> dict[str, Any]:
    return {"unavailable_roles": data.get("unavailable_roles", [])}


def _advice_attrs(data: dict[str, Any]) -> dict[str, Any]:
    advice = data.get("advice", [])
    messages = [a["message"] for a in advice]
    return {
        "advice": advice,
        "pending_nudges": data.get("pending_nudges", []),
        "presence_home": data.get("presence_home"),
        "summary": messages[0] if messages else "No advice right now.",
        # Ready to drop straight into a Markdown card: one bullet per advice, each
        # on its own line. Falls back to a plain line when there's nothing to say.
        "advice_markdown": (
            "\n".join(f"- {m}" for m in messages)
            if messages
            else "No advice right now."
        ),
    }


SENSORS: tuple[GHandalfSensorDescription, ...] = (
    GHandalfSensorDescription(
        key="solar_surplus",
        translation_key="solar_surplus",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: data.get("surplus_w"),
    ),
    GHandalfSensorDescription(
        key="net_grid_power",
        translation_key="net_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: data.get("net_grid_w"),
    ),
    GHandalfSensorDescription(
        key="active_advice",
        translation_key="active_advice",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.get("advice", [])),
        attrs_fn=_advice_attrs,
    ),
    GHandalfSensorDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status,
        attrs_fn=_status_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GHandalfConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up gHAndalf sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GHandalfSensor(coordinator, entry, description) for description in SENSORS
    )


class GHandalfSensor(CoordinatorEntity[GHandalfCoordinator], SensorEntity):
    """A derived/diagnostic sensor backed by the coordinator snapshot."""

    _attr_has_entity_name = True
    entity_description: GHandalfSensorDescription

    def __init__(
        self,
        coordinator: GHandalfCoordinator,
        entry: GHandalfConfigEntry,
        description: GHandalfSensorDescription,
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
    def native_value(self) -> StateType:
        """Return the derived value from the latest snapshot."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for sensors that expose them."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
