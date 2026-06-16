"""Tests for the declarative config schema."""

from __future__ import annotations

import voluptuous as vol

from custom_components.ghandalf.config_schema import (
    MENU_OPTIONS,
    SECTION_BY_ID,
    section_keys,
    section_schema,
    setup_schema,
)
from custom_components.ghandalf.const import (
    CONF_CONSUMPTION_POWER,
    CONF_DEHUMIDIFIER_SENSORS,
    CONF_PV_POWER,
    CONF_SURPLUS_THRESHOLD_W,
)


def test_setup_schema_is_just_the_essentials():
    keys = set(setup_schema().schema)
    assert keys == {CONF_PV_POWER, CONF_CONSUMPTION_POWER}


def test_setup_essentials_are_required():
    for marker in setup_schema().schema:
        assert isinstance(marker, vol.Required)


def test_menu_matches_sections():
    assert list(SECTION_BY_ID) == MENU_OPTIONS


def test_section_schema_contains_its_fields():
    keys = set(section_schema(SECTION_BY_ID["air_quality"]).schema)
    assert CONF_DEHUMIDIFIER_SENSORS in keys
    assert CONF_SURPLUS_THRESHOLD_W not in keys  # that lives in the energy section


def test_section_keys_helper():
    assert CONF_SURPLUS_THRESHOLD_W in section_keys(SECTION_BY_ID["energy"])


def test_every_field_key_is_unique_across_sections():
    seen: list[str] = []
    for section in SECTION_BY_ID.values():
        seen.extend(section_keys(section))
    assert len(seen) == len(set(seen))  # no key owned by two sections
