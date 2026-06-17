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

# Notifications (optional): HA notify entities to push each fired nudge to (via
# notify.send_message). Mapping a target is the on-switch — with none set,
# gHAndalf stays silent and advice lives only on the sensor.
CONF_NOTIFY_TARGETS: Final = "notify_targets"
# Optional: also post each nudge to Home Assistant's own notification panel (the
# bell in the web UI) via persistent_notification. Independent of the phone push.
CONF_NOTIFY_PERSISTENT: Final = "notify_persistent"
DEFAULT_NOTIFY_PERSISTENT: Final = False
# Title shown on every pushed nudge.
NOTIFY_TITLE: Final = "🧙 gHAndalf"

# Air quality & comfort (pillar 2). Humidity sensors for rooms that have a
# dehumidifier — high humidity in one of these prompts "run the dehumidifier".
CONF_DEHUMIDIFIER_SENSORS: Final = "dehumidifier_sensors"
# Optional plug-power sensors for those dehumidifiers. Paired to a humidity room
# by shared HA area; if the plug draws power, the room's advice is suppressed
# (it's already running). Generic — no room is hardcoded.
CONF_DEHUMIDIFIER_POWER_SENSORS: Final = "dehumidifier_power_sensors"
# CO2 sensors (per room) — high CO2 prompts "open a window". Window sensors are
# paired by area to suppress the nudge when a window in that room is already open.
CONF_CO2_SENSORS: Final = "co2_sensors"
CONF_WINDOW_SENSORS: Final = "window_sensors"
# Outdoor reference, as priority-ordered lists (first available entity wins) so a
# local sensor can be preferred with a weather service as fallback. Temperature
# is surfaced in the ventilate message and, with humidity, decides whether opening
# a window is actually worth it (see the ventilate gates below).
CONF_OUTDOOR_TEMP_SENSORS: Final = "outdoor_temp_sensors"
CONF_OUTDOOR_HUMIDITY_SENSORS: Final = "outdoor_humidity_sensors"
# Optional indoor temperature/humidity, paired to a CO2 room by shared HA area.
# Used to compare indoor vs outdoor absolute humidity so we don't advise airing a
# room out when that would only make it more humid.
CONF_INDOOR_TEMP_SENSORS: Final = "indoor_temp_sensors"
CONF_INDOOR_HUMIDITY_SENSORS: Final = "indoor_humidity_sensors"
# Optional occupancy/motion sensors, paired to a CO2 room by shared HA area, so we
# only nudge to air out a room that someone is actually in (or just left).
CONF_OCCUPANCY_SENSORS: Final = "occupancy_sensors"

# --- Tunables (options flow) ------------------------------------------------
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SURPLUS_THRESHOLD_W: Final = "surplus_threshold_w"
CONF_HUMIDITY_THRESHOLD_PCT: Final = "humidity_threshold_pct"
CONF_HUMIDITY_OFF_THRESHOLD_PCT: Final = "humidity_off_threshold_pct"
CONF_DEHUMIDIFIER_RUNNING_WATTS: Final = "dehumidifier_running_watts"
CONF_CO2_THRESHOLD_PPM: Final = "co2_threshold_ppm"
# Outdoor temperature band within which airing a room out is worthwhile; outside
# it (too cold / too hot) the ventilate nudge is suppressed.
CONF_VENTILATE_MIN_OUTDOOR_TEMP_C: Final = "ventilate_min_outdoor_temp_c"
CONF_VENTILATE_MAX_OUTDOOR_TEMP_C: Final = "ventilate_max_outdoor_temp_c"
# Opt-in: only nudge to air out a room that's currently occupied. Off by default
# because high CO2 is worth clearing even if you're in the next room or about to
# walk in. When off, the occupancy sensors/grace below have no effect.
CONF_REQUIRE_OCCUPANCY: Final = "require_occupancy"
# How long after an occupancy sensor goes quiet a room still counts as occupied —
# covers a present-but-still person whose motion sensor has cleared.
CONF_OCCUPANCY_GRACE_MINUTES: Final = "occupancy_grace_minutes"

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
DEFAULT_CO2_THRESHOLD_PPM: Final = 1000  # ppm above which to suggest ventilating
# Below the min it's too cold to bother (heat loss); above the max, outdoor air
# won't freshen/cool. Both editable — set the min lower for aggressive winter CO2
# control (brief "shock airing" is fine even when cold).
DEFAULT_VENTILATE_MIN_OUTDOOR_TEMP_C: Final = 3
DEFAULT_VENTILATE_MAX_OUTDOOR_TEMP_C: Final = 28
# A room stays "occupied" for this long after its last motion, so we don't treat a
# sitting-still person as gone. Edit to taste.
DEFAULT_OCCUPANCY_GRACE_MINUTES: Final = 15
DEFAULT_REQUIRE_OCCUPANCY: Final = False  # occupancy gate is opt-in

DEFAULT_QUIET_START: Final = "22:00:00"
DEFAULT_QUIET_END: Final = "07:00:00"
DEFAULT_DEBOUNCE_SECONDS: Final = (
    300  # a condition must persist this long before firing
)
DEFAULT_COOLDOWN_MINUTES: Final = 60  # min gap between repeats of the same advice
DEFAULT_MAX_NUDGES_PER_DAY: Final = 8  # global daily cap across all categories
# Per-category daily cap. Not exposed in the UI yet (kept simple); see REQUIREMENTS §8.
DEFAULT_MAX_PER_CATEGORY_PER_DAY: Final = 3
