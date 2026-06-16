"""Pure helper functions for gHAndalf.

Kept free of Home Assistant runtime objects (other than reading a state's
string value) so they are trivially unit- and mutation-testable.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.config_entries import ConfigEntry

# Home Assistant sentinel states that mean "no usable reading". This is a
# readability / fast-path layer only: float() below also rejects every one of
# these, so mutating these literals produces *equivalent mutants* (no change in
# behaviour). We tell mutmut not to mutate the line rather than chase mutants no
# test could ever kill.
_NON_NUMERIC = frozenset({"unknown", "unavailable", "none", ""})  # pragma: no mutate


def get_conf(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Return the effective config value for ``key``.

    Options (set later in the options flow) take precedence over the original
    setup data, which takes precedence over ``default``. This is what lets the
    user retune everything from the UI without re-adding the integration.
    """
    if key in entry.options:
        return entry.options[key]
    if key in entry.data:
        return entry.data[key]
    return default


def parse_float(raw: str | float | int | None) -> float | None:
    """Best-effort parse of a HA state value into a float.

    Returns ``None`` for missing/unknown/unavailable/non-numeric values rather
    than raising, so a single flaky sensor never breaks a whole update cycle.
    """
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    text = str(raw).strip()
    if text.lower() in _NON_NUMERIC:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def solar_surplus_w(pv_w: float | None, consumption_w: float | None) -> float | None:
    """PV production minus household consumption, in watts.

    ``None`` if either input is missing. May be negative (importing).
    """
    if pv_w is None or consumption_w is None:
        return None
    return pv_w - consumption_w


def net_grid_w(import_w: float | None, export_w: float | None) -> float | None:
    """Signed grid power: positive = importing, negative = exporting.

    Tolerates either side being missing (treats a missing side as 0) but returns
    ``None`` when both are missing, so we don't fabricate a reading from nothing.
    """
    if import_w is None and export_w is None:
        return None
    return (import_w or 0.0) - (export_w or 0.0)


def parse_time(value: str | time | None, default: time | None = None) -> time | None:
    """Parse an ``"HH:MM[:SS]"`` string (as a TimeSelector returns) into a time."""
    if isinstance(value, time):
        return value
    if not value:
        return default
    parts = str(value).split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
        return time(hour, minute, second)
    except (ValueError, IndexError):
        return default


def in_quiet_hours(now_t: time, start: time, end: time) -> bool:
    """Whether ``now_t`` falls in the [start, end) quiet window.

    Handles a window that wraps past midnight (e.g. 22:00-07:00). A zero-length
    window (start == end) means "disabled" and is never quiet.
    """
    if start == end:
        return False
    # `<` vs `<=` here is an equivalent mutant: start == end already returned above.
    if start < end:  # pragma: no mutate
        return start <= now_t < end
    return now_t >= start or now_t < end
