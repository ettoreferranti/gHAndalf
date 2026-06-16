"""The rule engine: pure functions that turn a snapshot into advice candidates.

Each rule takes the coordinator snapshot and the effective config (a plain
mapping) and returns an ``AdviceCandidate`` or ``None``. Pure and HA-free, so
they unit- and mutation-test cleanly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_SURPLUS_THRESHOLD_W,
    DEFAULT_DEHUMIDIFIER_RUNNING_WATTS,
    DEFAULT_HUMIDITY_THRESHOLD_PCT,
    DEFAULT_SURPLUS_THRESHOLD_W,
)
from .models import AdviceCandidate, Category, Urgency

# Type aliases only — mutating them to None is an equivalent mutant (annotations
# aren't enforced at runtime).
Snapshot = Mapping[str, Any]  # pragma: no mutate
Config = Mapping[str, Any]  # pragma: no mutate


def _exporting_w(snapshot: Snapshot) -> float | None:
    """Watts currently flowing to the grid (0 if importing), or None if unknown.

    Prefers the signed grid reading (which accounts for the battery absorbing
    surplus); falls back to raw PV-minus-consumption if grid isn't mapped.
    """
    net = snapshot.get("net_grid_w")
    if net is not None:
        return max(0.0, -net)
    surplus = snapshot.get("surplus_w")
    if surplus is not None:
        return max(0.0, surplus)
    return None


def rule_solar_surplus(snapshot: Snapshot, cfg: Config) -> AdviceCandidate | None:
    """Suggest running a flexible load when meaningful solar is going to grid."""
    exporting = _exporting_w(snapshot)
    if exporting is None:
        return None
    threshold = cfg.get(CONF_SURPLUS_THRESHOLD_W, DEFAULT_SURPLUS_THRESHOLD_W)
    if exporting < threshold:
        return None
    watts = round(exporting)
    return AdviceCandidate(
        key="solar_surplus",
        category=Category.ENERGY,
        urgency=Urgency.INFO,
        message=(
            f"You're sending about {watts} W of solar to the grid right now. "
            "Good time to run a flexible load — dishwasher, laundry, or top up the car."
        ),
        data={"exporting_w": exporting, "threshold_w": threshold},
    )


def rule_dehumidifier(snapshot: Snapshot, cfg: Config) -> list[AdviceCandidate]:
    """Suggest running the dehumidifier in any mapped room above the threshold.

    Unlike the single-result rules, this fans out over the mapped dehumidifier
    rooms (snapshot ``dehumidifier_rooms``), one candidate per humid room.
    """
    rooms = snapshot.get("dehumidifier_rooms") or []
    threshold = cfg.get(CONF_HUMIDITY_THRESHOLD_PCT, DEFAULT_HUMIDITY_THRESHOLD_PCT)
    running_watts = cfg.get(
        CONF_DEHUMIDIFIER_RUNNING_WATTS, DEFAULT_DEHUMIDIFIER_RUNNING_WATTS
    )
    out: list[AdviceCandidate] = []
    for room in rooms:
        humidity = room.get("humidity")
        if humidity is None or humidity < threshold:
            continue
        power_w = room.get("power_w")
        if power_w is not None and power_w >= running_watts:
            continue  # the dehumidifier is already running — don't nag
        out.append(
            AdviceCandidate(
                key=f"dehumidifier:{room['entity_id']}",
                category=Category.AIR_QUALITY,
                urgency=Urgency.ACT,
                message=(
                    f"Humidity in {room['name']} is {round(humidity)}% "
                    f"(above {threshold:g}%). Time to run the dehumidifier."
                ),
                data={
                    "room": room["name"],
                    "humidity": humidity,
                    "threshold": threshold,
                    "power_w": power_w,
                },
            )
        )
    return out


# Single-result rules (return one candidate or None).
RULES = (rule_solar_surplus,)
# Multi-result rules (return a list of candidates).
MULTI_RULES = (rule_dehumidifier,)


def evaluate_rules(snapshot: Snapshot, cfg: Config) -> list[AdviceCandidate]:
    """Run every rule and collect the candidates that fired."""
    candidates: list[AdviceCandidate] = []
    for rule in RULES:
        candidate = rule(snapshot, cfg)
        if candidate is not None:
            candidates.append(candidate)
    for multi_rule in MULTI_RULES:
        candidates.extend(multi_rule(snapshot, cfg))
    return candidates
