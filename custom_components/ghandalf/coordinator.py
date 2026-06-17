"""Coordinator that samples the mapped HA entities and derives values.

This is the heart of the "HA-native, source-agnostic" principle: gHAndalf reads
the *live* state machine for whichever entities the user mapped — it never talks
to a vendor API. Each cycle it also runs the rule engine and the nudge gate.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_SOC,
    CONF_CO2_SENSORS,
    CONF_CO2_THRESHOLD_PPM,
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
    CONF_INDOOR_HUMIDITY_SENSORS,
    CONF_INDOOR_TEMP_SENSORS,
    CONF_MAX_NUDGES_PER_DAY,
    CONF_OCCUPANCY_GRACE_MINUTES,
    CONF_OCCUPANCY_SENSORS,
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMP_SENSORS,
    CONF_PERSONS,
    CONF_PV_POWER,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCAN_INTERVAL,
    CONF_SURPLUS_THRESHOLD_W,
    CONF_VENTILATE_MAX_OUTDOOR_TEMP_C,
    CONF_VENTILATE_MIN_OUTDOOR_TEMP_C,
    CONF_WINDOW_SENSORS,
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_MAX_NUDGES_PER_DAY,
    DEFAULT_MAX_PER_CATEGORY_PER_DAY,
    DEFAULT_OCCUPANCY_GRACE_MINUTES,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .helpers import (
    get_conf,
    net_grid_w,
    occupied_within,
    parse_float,
    parse_time,
    solar_surplus_w,
)
from .nudge_gate import NudgeGate
from .rules import evaluate_rules

_LOGGER = logging.getLogger(__name__)

# Roles read as plain numeric sensors. Maps the result key -> config key.
_NUMERIC_ROLES: dict[str, str] = {
    "pv_w": CONF_PV_POWER,
    "consumption_w": CONF_CONSUMPTION_POWER,
    "grid_import_w": CONF_GRID_IMPORT_POWER,
    "grid_export_w": CONF_GRID_EXPORT_POWER,
    "battery_soc": CONF_BATTERY_SOC,
}

# Config keys the rule engine reads, surfaced as a plain mapping.
_RULE_CONFIG_KEYS = (
    CONF_SURPLUS_THRESHOLD_W,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_HUMIDITY_OFF_THRESHOLD_PCT,
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_CO2_THRESHOLD_PPM,
    CONF_VENTILATE_MIN_OUTDOOR_TEMP_C,
    CONF_VENTILATE_MAX_OUTDOOR_TEMP_C,
)


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
        self.gate = self._build_gate()

    def _build_gate(self) -> NudgeGate:
        return NudgeGate(
            quiet_start=parse_time(
                get_conf(self.entry, CONF_QUIET_START, DEFAULT_QUIET_START),
                parse_time(DEFAULT_QUIET_START),
            ),
            quiet_end=parse_time(
                get_conf(self.entry, CONF_QUIET_END, DEFAULT_QUIET_END),
                parse_time(DEFAULT_QUIET_END),
            ),
            debounce_seconds=int(
                get_conf(self.entry, CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS)
            ),
            cooldown_minutes=int(
                get_conf(self.entry, CONF_COOLDOWN_MINUTES, DEFAULT_COOLDOWN_MINUTES)
            ),
            max_per_day=int(
                get_conf(
                    self.entry, CONF_MAX_NUDGES_PER_DAY, DEFAULT_MAX_NUDGES_PER_DAY
                )
            ),
            max_per_category_per_day=DEFAULT_MAX_PER_CATEGORY_PER_DAY,
        )

    def _read_role(self, config_key: str) -> float | None:
        """Read one mapped entity's current value as a float (or None)."""
        entity_id = get_conf(self.entry, config_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return parse_float(state.state)

    def _first_available(self, config_key: str) -> float | None:
        """First parseable reading across a priority-ordered list of entities.

        Lets the user prefer a local sensor and fall back to a weather service:
        the first entity that yields a usable number wins.
        """
        for entity_id in get_conf(self.entry, config_key) or []:
            state = self.hass.states.get(entity_id)
            value = parse_float(state.state) if state else None
            if value is not None:
                return value
        return None

    def _first_value_by_area(self, config_key: str) -> dict[str, float]:
        """Area id -> first parseable reading among that area's mapped sensors."""
        values: dict[str, float] = {}
        for entity_id in get_conf(self.entry, config_key) or []:
            area_id = self._area_id(entity_id)
            if area_id is None or area_id in values:
                continue
            state = self.hass.states.get(entity_id)
            value = parse_float(state.state) if state else None
            if value is not None:
                values[area_id] = value
        return values

    def _presence_home(self) -> bool:
        """True if no persons are mapped, or any mapped person is home."""
        persons = get_conf(self.entry, CONF_PERSONS) or []
        if not persons:
            return True
        return any(
            (state := self.hass.states.get(person)) is not None
            and state.state == "home"
            for person in persons
        )

    def _area_id(self, entity_id: str) -> str | None:
        """The HA area id for an entity (its own, else its device's)."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            return None
        if entry.area_id is not None:
            return entry.area_id
        if entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            return device.area_id if device else None
        return None

    def _room_name(self, entity_id: str) -> str:
        """Human-readable room for an entity: its HA area, else friendly name.

        Using the area means the label follows the entity if it's physically
        moved and re-assigned in HA (e.g. a humidity sensor moved to the basement).
        """
        area_id = self._area_id(entity_id)
        if area_id:
            area = ar.async_get(self.hass).async_get_area(area_id)
            if area:
                return area.name
        state = self.hass.states.get(entity_id)
        if state:
            return state.attributes.get("friendly_name", entity_id)
        return entity_id

    def _power_by_area(self) -> dict[str, float]:
        """Max plug-power reading per area, across the mapped dehumidifier plugs."""
        powers: dict[str, float] = {}
        for entity_id in get_conf(self.entry, CONF_DEHUMIDIFIER_POWER_SENSORS) or []:
            area_id = self._area_id(entity_id)
            if area_id is None:
                continue
            state = self.hass.states.get(entity_id)
            power = parse_float(state.state) if state else None
            if power is None:
                continue
            powers[area_id] = max(powers.get(area_id, power), power)
        return powers

    def _read_dehumidifier_rooms(self) -> list[dict[str, Any]]:
        """Read each mapped dehumidifier-room humidity sensor.

        Pairs a plug-power reading by shared HA area, so the rule can tell when
        the dehumidifier is already running.
        """
        powers = self._power_by_area()
        rooms: list[dict[str, Any]] = []
        for entity_id in get_conf(self.entry, CONF_DEHUMIDIFIER_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            area_id = self._area_id(entity_id)
            rooms.append(
                {
                    "entity_id": entity_id,
                    "name": self._room_name(entity_id),
                    "humidity": parse_float(state.state) if state else None,
                    "power_w": powers.get(area_id) if area_id is not None else None,
                }
            )
        return rooms

    def _open_window_areas(self) -> set[str]:
        """Area ids that currently have at least one mapped window open."""
        areas: set[str] = set()
        for entity_id in get_conf(self.entry, CONF_WINDOW_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == "on":
                area_id = self._area_id(entity_id)
                if area_id is not None:
                    areas.add(area_id)
        return areas

    def _occupancy_by_area(self) -> dict[str, bool]:
        """Area id -> occupied, for areas with at least one mapped occupancy sensor.

        Only areas that *have* a mapped sensor appear, so a CO2 room with no
        occupancy sensor is left to default to occupied (the gate stays open).
        Counts a room as occupied while it's within the grace window of its last
        motion, not just on a live ``on``.
        """
        grace = float(
            get_conf(
                self.entry,
                CONF_OCCUPANCY_GRACE_MINUTES,
                DEFAULT_OCCUPANCY_GRACE_MINUTES,
            )
        )
        now = dt_util.now()
        occupancy: dict[str, bool] = {}
        for entity_id in get_conf(self.entry, CONF_OCCUPANCY_SENSORS) or []:
            area_id = self._area_id(entity_id)
            if area_id is None:
                continue
            state = self.hass.states.get(entity_id)
            occupied = state is not None and occupied_within(
                state.state, state.last_changed, now, grace
            )
            occupancy[area_id] = occupancy.get(area_id, False) or occupied
        return occupancy

    def _read_co2_rooms(self) -> list[dict[str, Any]]:
        """Read each mapped CO2 sensor, flagging whether its room is being aired.

        Indoor temperature/humidity are paired in by shared HA area so the rule
        can compare indoor vs outdoor absolute humidity per room; occupancy is
        paired the same way so we don't nudge to air out an empty room.
        """
        open_areas = self._open_window_areas()
        indoor_temps = self._first_value_by_area(CONF_INDOOR_TEMP_SENSORS)
        indoor_humidities = self._first_value_by_area(CONF_INDOOR_HUMIDITY_SENSORS)
        occupancy = self._occupancy_by_area()
        rooms: list[dict[str, Any]] = []
        for entity_id in get_conf(self.entry, CONF_CO2_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            area_id = self._area_id(entity_id)
            rooms.append(
                {
                    "entity_id": entity_id,
                    "name": self._room_name(entity_id),
                    "ppm": parse_float(state.state) if state else None,
                    "window_open": area_id is not None and area_id in open_areas,
                    "indoor_temp": indoor_temps.get(area_id)
                    if area_id is not None
                    else None,
                    "indoor_humidity": indoor_humidities.get(area_id)
                    if area_id is not None
                    else None,
                    # Default-open: an area with no mapped occupancy sensor (or a
                    # CO2 sensor with no area) counts as occupied.
                    "occupied": occupancy.get(area_id, True)
                    if area_id is not None
                    else True,
                }
            )
        return rooms

    def _rule_config(self) -> dict[str, Any]:
        # Omit unset keys so rules' own ``cfg.get(key, DEFAULT)`` fallbacks apply
        # (injecting an explicit None would shadow those defaults).
        cfg: dict[str, Any] = {}
        for key in _RULE_CONFIG_KEYS:
            value = get_conf(self.entry, key)
            if value is not None:
                cfg[key] = value
        return cfg

    async def _async_update_data(self) -> dict[str, Any]:
        """Sample mapped entities, derive values, and run rules + nudge gate.

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

        unavailable = [
            conf_key
            for key, conf_key in _NUMERIC_ROLES.items()
            if get_conf(self.entry, conf_key) and values[key] is None
        ]
        values["unavailable_roles"] = unavailable
        values["dehumidifier_rooms"] = self._read_dehumidifier_rooms()
        values["co2_rooms"] = self._read_co2_rooms()
        values["outdoor_temp"] = self._first_available(CONF_OUTDOOR_TEMP_SENSORS)
        values["outdoor_humidity"] = self._first_available(
            CONF_OUTDOOR_HUMIDITY_SENSORS
        )

        # Rule engine -> candidates; nudge gate -> what would fire now.
        candidates = evaluate_rules(values, self._rule_config())
        presence_home = self._presence_home()
        fired = self.gate.evaluate(candidates, dt_util.now(), presence_home)

        values["presence_home"] = presence_home
        values["advice"] = [c.as_dict() for c in candidates]
        values["pending_nudges"] = [c.key for c in fired]

        return values
