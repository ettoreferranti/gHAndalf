"""Constants for the gHAndalf integration.

Nothing here is a behavioural value baked into logic — every tunable below is a
*default* that the user can override from the config/options UI. See
``REQUIREMENTS.md`` for the design rationale.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ghandalf"

# --- Configuration keys (entity-role mapping) -------------------------------
# Energy / solar roles. Each maps a gHAndalf "role" to a real HA entity id,
# chosen by the user in the UI. The component reads live state from these.
CONF_PV_POWER: Final = "pv_production_power"
CONF_CONSUMPTION_POWER: Final = "household_consumption_power"
CONF_GRID_IMPORT_POWER: Final = "grid_import_power"
CONF_GRID_EXPORT_POWER: Final = "grid_export_power"
CONF_BATTERY_SOC: Final = "battery_soc"

# Presence (optional): persons used to decide "is anyone home" for nudge-gating.
CONF_PERSONS: Final = "persons"

# Air quality & comfort (pillar 2). Humidity sensors for rooms that have a
# dehumidifier — high humidity in one of these prompts "run the dehumidifier".
CONF_DEHUMIDIFIER_SENSORS: Final = "dehumidifier_sensors"
# Optional plug-power sensors for those dehumidifiers. Paired to a humidity room
# by shared HA area; if the plug draws power, the room's advice is suppressed
# (it's already running). Generic — no room is hardcoded.
CONF_DEHUMIDIFIER_POWER_SENSORS: Final = "dehumidifier_power_sensors"

# --- Tunables (options flow) ------------------------------------------------
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SURPLUS_THRESHOLD_W: Final = "surplus_threshold_w"
CONF_HUMIDITY_THRESHOLD_PCT: Final = "humidity_threshold_pct"
CONF_HUMIDITY_OFF_THRESHOLD_PCT: Final = "humidity_off_threshold_pct"
CONF_DEHUMIDIFIER_RUNNING_WATTS: Final = "dehumidifier_running_watts"

# Nudge-gate tunables (anti-alert-fatigue).
CONF_QUIET_START: Final = "quiet_hours_start"
CONF_QUIET_END: Final = "quiet_hours_end"
CONF_DEBOUNCE_SECONDS: Final = "debounce_seconds"
CONF_COOLDOWN_MINUTES: Final = "cooldown_minutes"
CONF_MAX_NUDGES_PER_DAY: Final = "max_nudges_per_day"

# --- Defaults (initial values only; all editable in the UI) -----------------
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

DEFAULT_SURPLUS_THRESHOLD_W: Final = 1000  # W of PV surplus considered "worth using"
DEFAULT_HUMIDITY_THRESHOLD_PCT: Final = 60  # %RH above which to suggest dehumidifying
DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT: Final = (
    45  # %RH at/below which to suggest turning off
)
DEFAULT_DEHUMIDIFIER_RUNNING_WATTS: Final = 10  # plug draw above which it's "running"

DEFAULT_QUIET_START: Final = "22:00:00"
DEFAULT_QUIET_END: Final = "07:00:00"
DEFAULT_DEBOUNCE_SECONDS: Final = (
    300  # a condition must persist this long before firing
)
DEFAULT_COOLDOWN_MINUTES: Final = 60  # min gap between repeats of the same advice
DEFAULT_MAX_NUDGES_PER_DAY: Final = 8  # global daily cap across all categories
# Per-category daily cap. Not exposed in the UI yet (kept simple); see REQUIREMENTS §8.
DEFAULT_MAX_PER_CATEGORY_PER_DAY: Final = 3
