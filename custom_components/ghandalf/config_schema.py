"""Declarative config schema — the single source of truth for what's configurable.

Config is organised into domain **sections** (Energy, Air quality, …). Each rule
contributes its fields to the relevant section here; the config/options flows are
generic and assemble their forms from these declarations, so adding a rule never
means editing imperative form code. Field help text lives in ``strings.json``
under each step's ``data_description`` so every setting explains itself in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.helpers import selector
import voluptuous as vol

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
    CONF_MAX_NUDGES_PER_DAY,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PERSONS,
    CONF_PV_POWER,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCAN_INTERVAL,
    CONF_SURPLUS_THRESHOLD_W,
    CONF_WINDOW_SENSORS,
    DEFAULT_CO2_THRESHOLD_PPM,
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
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


@dataclass(frozen=True)
class Field:
    """One configurable value: a config key, its selector, and how it's offered."""

    key: str
    selector: selector.Selector
    default: object = vol.UNDEFINED
    required: bool = False
    # Whether to ask for it during initial setup (vs only later via Configure).
    in_setup: bool = False


@dataclass(frozen=True)
class Section:
    """A domain group of fields, shown as one step in the options menu."""

    step_id: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


# --- selector factories -----------------------------------------------------
def _sensor(device_class: str, multiple: bool = False) -> selector.Selector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor", device_class=device_class, multiple=multiple
        )
    )


def _persons() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="person", multiple=True)
    )


def _windows() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="binary_sensor",
            device_class=["window", "door", "opening", "garage_door"],
            multiple=True,
        )
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


# --- the sections (each rule contributes its fields to one of these) --------
ENERGY = Section(
    "energy",
    (
        Field(CONF_PV_POWER, _sensor("power"), required=True, in_setup=True),
        Field(CONF_CONSUMPTION_POWER, _sensor("power"), required=True, in_setup=True),
        Field(CONF_GRID_IMPORT_POWER, _sensor("power")),
        Field(CONF_GRID_EXPORT_POWER, _sensor("power")),
        Field(CONF_BATTERY_SOC, _sensor("battery")),
        Field(
            CONF_SURPLUS_THRESHOLD_W,
            _number(0, 20000, 100, "W"),
            default=DEFAULT_SURPLUS_THRESHOLD_W,
        ),
    ),
)

AIR_QUALITY = Section(
    "air_quality",
    (
        Field(CONF_DEHUMIDIFIER_SENSORS, _sensor("humidity", multiple=True)),
        Field(CONF_DEHUMIDIFIER_POWER_SENSORS, _sensor("power", multiple=True)),
        Field(
            CONF_HUMIDITY_THRESHOLD_PCT,
            _number(0, 100, 1, "%"),
            default=DEFAULT_HUMIDITY_THRESHOLD_PCT,
        ),
        Field(
            CONF_HUMIDITY_OFF_THRESHOLD_PCT,
            _number(0, 100, 1, "%"),
            default=DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT,
        ),
        Field(
            CONF_DEHUMIDIFIER_RUNNING_WATTS,
            _number(0, 5000, 5, "W"),
            default=DEFAULT_DEHUMIDIFIER_RUNNING_WATTS,
        ),
        Field(CONF_CO2_SENSORS, _sensor("carbon_dioxide", multiple=True)),
        Field(CONF_WINDOW_SENSORS, _windows()),
        Field(CONF_OUTDOOR_TEMP_SENSOR, _sensor("temperature")),
        Field(
            CONF_CO2_THRESHOLD_PPM,
            _number(0, 5000, 50, "ppm"),
            default=DEFAULT_CO2_THRESHOLD_PPM,
        ),
    ),
)

PRESENCE = Section("presence", (Field(CONF_PERSONS, _persons()),))

ADVANCED = Section(
    "advanced",
    (
        Field(
            CONF_SCAN_INTERVAL,
            _number(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL, 5, "s"),
            default=DEFAULT_SCAN_INTERVAL,
        ),
        Field(CONF_QUIET_START, selector.TimeSelector(), default=DEFAULT_QUIET_START),
        Field(CONF_QUIET_END, selector.TimeSelector(), default=DEFAULT_QUIET_END),
        Field(
            CONF_DEBOUNCE_SECONDS,
            _number(0, 3600, 30, "s"),
            default=DEFAULT_DEBOUNCE_SECONDS,
        ),
        Field(
            CONF_COOLDOWN_MINUTES,
            _number(0, 1440, 5, "min"),
            default=DEFAULT_COOLDOWN_MINUTES,
        ),
        Field(
            CONF_MAX_NUDGES_PER_DAY,
            _number(1, 50, 1, ""),
            default=DEFAULT_MAX_NUDGES_PER_DAY,
        ),
    ),
)

SECTIONS: tuple[Section, ...] = (ENERGY, AIR_QUALITY, PRESENCE, ADVANCED)
SECTION_BY_ID: dict[str, Section] = {s.step_id: s for s in SECTIONS}
MENU_OPTIONS: list[str] = [s.step_id for s in SECTIONS]


def _marker(f: Field) -> vol.Marker:
    if f.required:
        return vol.Required(f.key)
    if f.default is not vol.UNDEFINED:
        return vol.Optional(f.key, default=f.default)
    return vol.Optional(f.key)


def section_schema(section: Section) -> vol.Schema:
    """Voluptuous schema for one section's fields."""
    return vol.Schema({_marker(f): f.selector for f in section.fields})


def setup_schema() -> vol.Schema:
    """Schema for the initial setup step — only the ``in_setup`` fields."""
    fields = [f for s in SECTIONS for f in s.fields if f.in_setup]
    return vol.Schema({_marker(f): f.selector for f in fields})


def section_keys(section: Section) -> set[str]:
    """The config keys owned by a section (used to replace them cleanly on save)."""
    return {f.key for f in section.fields}
