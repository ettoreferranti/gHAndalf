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

# --- Tunables (options flow) ------------------------------------------------
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SURPLUS_THRESHOLD_W: Final = "surplus_threshold_w"

# --- Defaults (initial values only; all editable in the UI) -----------------
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

DEFAULT_SURPLUS_THRESHOLD_W: Final = 1000  # W of PV surplus considered "worth using"
