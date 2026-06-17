"""The rule engine: pure functions that turn a snapshot into advice candidates.

Each rule takes the coordinator snapshot and the effective config (a plain
mapping) and returns an ``AdviceCandidate`` or ``None``. Pure and HA-free, so
they unit- and mutation-test cleanly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_CO2_THRESHOLD_PPM,
    CONF_DEHUMIDIFIER_RUNNING_WATTS,
    CONF_HUMIDITY_OFF_THRESHOLD_PCT,
    CONF_HUMIDITY_THRESHOLD_PCT,
    CONF_PRICE_MARGIN_PCT,
    CONF_REQUIRE_OCCUPANCY,
    CONF_SURPLUS_THRESHOLD_W,
    CONF_VENTILATE_MAX_OUTDOOR_TEMP_C,
    CONF_VENTILATE_MIN_OUTDOOR_TEMP_C,
    DEFAULT_CO2_THRESHOLD_PPM,
    DEFAULT_DEHUMIDIFIER_RUNNING_WATTS,
    DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT,
    DEFAULT_HUMIDITY_THRESHOLD_PCT,
    DEFAULT_PRICE_MARGIN_PCT,
    DEFAULT_REQUIRE_OCCUPANCY,
    DEFAULT_SURPLUS_THRESHOLD_W,
    DEFAULT_VENTILATE_MAX_OUTDOOR_TEMP_C,
    DEFAULT_VENTILATE_MIN_OUTDOOR_TEMP_C,
)
from .helpers import absolute_humidity
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


def rule_grid_price(snapshot: Snapshot, cfg: Config) -> AdviceCandidate | None:
    """Nudge to use or defer flexible load based on the live electricity price.

    Tariff-source-agnostic: compares the current price against the day's average
    (both plain sensor readings) with a configurable margin. A flat tariff leaves
    current == average, so nothing fires; a stepped high/low tariff or 15-minute
    dynamic slots make cheap/pricey windows light up automatically — same rule,
    only the data changes.
    """
    price = snapshot.get("price_now")
    average = snapshot.get("price_avg")
    if price is None or average is None or average <= 0:
        return None
    margin = cfg.get(CONF_PRICE_MARGIN_PCT, DEFAULT_PRICE_MARGIN_PCT) / 100

    if price <= average * (1 - margin):
        pct = round((1 - price / average) * 100)
        return AdviceCandidate(
            key="grid_price_cheap",
            category=Category.ENERGY,
            urgency=Urgency.INFO,
            message=(
                f"Electricity is cheap right now ({price:g} CHF/kWh, about {pct}% "
                "below today's average) — good time for a flexible load like the "
                "dishwasher, laundry, or charging the car."
            ),
            data={"price": price, "average": average, "pct_from_avg": -pct},
        )
    if price >= average * (1 + margin):
        pct = round((price / average - 1) * 100)
        return AdviceCandidate(
            key="grid_price_expensive",
            category=Category.ENERGY,
            urgency=Urgency.INFO,
            message=(
                f"Electricity is pricey right now ({price:g} CHF/kWh, about {pct}% "
                "above today's average) — hold off on big flexible loads if you can."
            ),
            data={"price": price, "average": average, "pct_from_avg": pct},
        )
    return None


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
                    f"(at or above {threshold:g}%). Time to run the dehumidifier."
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


def rule_dehumidifier_off(snapshot: Snapshot, cfg: Config) -> list[AdviceCandidate]:
    """Suggest switching a dehumidifier off once its room is dry enough.

    Only fires for rooms whose plug shows the dehumidifier actually running (so
    we never tell you to turn off something that's already off, or a room with
    no plug to tell). The gap to the "run it" threshold is a hysteresis band.
    """
    rooms = snapshot.get("dehumidifier_rooms") or []
    off_threshold = cfg.get(
        CONF_HUMIDITY_OFF_THRESHOLD_PCT, DEFAULT_HUMIDITY_OFF_THRESHOLD_PCT
    )
    running_watts = cfg.get(
        CONF_DEHUMIDIFIER_RUNNING_WATTS, DEFAULT_DEHUMIDIFIER_RUNNING_WATTS
    )
    out: list[AdviceCandidate] = []
    for room in rooms:
        humidity = room.get("humidity")
        if humidity is None or humidity > off_threshold:
            continue
        power_w = room.get("power_w")
        if power_w is None or power_w < running_watts:
            continue  # not running (or unknown) — nothing to turn off
        out.append(
            AdviceCandidate(
                key=f"dehumidifier_off:{room['entity_id']}",
                category=Category.AIR_QUALITY,
                urgency=Urgency.INFO,
                message=(
                    f"Humidity in {room['name']} is {round(humidity)}% — "
                    "dry enough now, you can switch the dehumidifier off."
                ),
                data={
                    "room": room["name"],
                    "humidity": humidity,
                    "off_threshold": off_threshold,
                    "power_w": power_w,
                },
            )
        )
    return out


def _venting_blocked(room: Mapping[str, Any], snapshot: Snapshot, cfg: Config) -> bool:
    """Whether opening a window isn't worth it given the outdoor air right now.

    Two independent reasons, each applied only when its data is available (so the
    gate stays default-open and we never suppress on missing readings):

    * outdoor temperature is outside the configured comfort band (too cold to
      bother / too hot to freshen), or
    * outdoor air is more humid than the room, so airing it out would only import
      moisture. Compared via *absolute* humidity, which (unlike %RH) is
      comparable across the indoor/outdoor temperature difference.
    """
    outdoor_temp = snapshot.get("outdoor_temp")
    if outdoor_temp is not None:
        min_t = cfg.get(
            CONF_VENTILATE_MIN_OUTDOOR_TEMP_C, DEFAULT_VENTILATE_MIN_OUTDOOR_TEMP_C
        )
        max_t = cfg.get(
            CONF_VENTILATE_MAX_OUTDOOR_TEMP_C, DEFAULT_VENTILATE_MAX_OUTDOOR_TEMP_C
        )
        if outdoor_temp < min_t or outdoor_temp > max_t:
            return True
    indoor_ah = absolute_humidity(room.get("indoor_temp"), room.get("indoor_humidity"))
    outdoor_ah = absolute_humidity(outdoor_temp, snapshot.get("outdoor_humidity"))
    return indoor_ah is not None and outdoor_ah is not None and outdoor_ah > indoor_ah


def rule_co2_ventilate(snapshot: Snapshot, cfg: Config) -> list[AdviceCandidate]:
    """Suggest airing a room out when its CO2 is high and no window is open.

    Window state is paired to the room by HA area (in the coordinator), so we
    don't nag when the room is already being ventilated. The nudge is also held
    back when the outdoor air wouldn't actually help (see ``_venting_blocked``)
    and, *only if the optional occupancy gate is enabled*, when the room is
    empty. Outdoor temperature, if mapped, is added to the message for context.
    """
    rooms = snapshot.get("co2_rooms") or []
    threshold = cfg.get(CONF_CO2_THRESHOLD_PPM, DEFAULT_CO2_THRESHOLD_PPM)
    require_occupancy = cfg.get(CONF_REQUIRE_OCCUPANCY, DEFAULT_REQUIRE_OCCUPANCY)
    outdoor = snapshot.get("outdoor_temp")
    out: list[AdviceCandidate] = []
    for room in rooms:
        ppm = room.get("ppm")
        if ppm is None or ppm < threshold:
            continue
        if room.get("window_open"):
            continue  # already being aired out
        if require_occupancy and not room.get("occupied", True):
            continue  # opt-in: only nudge a room someone's actually in
        if _venting_blocked(room, snapshot, cfg):
            continue  # outdoor air too cold/hot, or more humid than the room
        message = (
            f"CO2 in {room['name']} is {round(ppm)} ppm — "
            "open a window for a few minutes to freshen the air."
        )
        if outdoor is not None:
            message += f" It's about {round(outdoor)}° outside."
        out.append(
            AdviceCandidate(
                key=f"co2:{room['entity_id']}",
                category=Category.AIR_QUALITY,
                urgency=Urgency.ACT,
                message=message,
                data={
                    "room": room["name"],
                    "ppm": ppm,
                    "threshold": threshold,
                    "outdoor_temp": outdoor,
                    "outdoor_humidity": snapshot.get("outdoor_humidity"),
                },
            )
        )
    return out


# Single-result rules (return one candidate or None).
RULES = (rule_solar_surplus, rule_grid_price)
# Multi-result rules (return a list of candidates).
MULTI_RULES = (rule_dehumidifier, rule_dehumidifier_off, rule_co2_ventilate)


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
