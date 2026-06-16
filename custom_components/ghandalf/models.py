"""Data models shared by the rule engine, nudge gate, and sensors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Category(StrEnum):
    """Coaching domain a piece of advice belongs to (drives per-category budgets)."""

    ENERGY = "energy"
    AIR_QUALITY = "air_quality"


class Urgency(StrEnum):
    """How strongly a piece of advice should be surfaced."""

    INFO = "info"
    ACT = "act"
    URGENT = "urgent"


@dataclass(frozen=True)
class AdviceCandidate:
    """One piece of advice a rule produced for the current snapshot.

    ``key`` is a stable identifier (e.g. ``"solar_surplus"`` or ``"co2:office"``)
    used by the nudge gate for debounce, cooldown, and dedupe. ``data`` carries
    the structured facts behind the message, for a future LLM narrator.
    """

    key: str
    category: Category
    urgency: Urgency
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly form for sensor attributes."""
        return {
            "key": self.key,
            "category": str(self.category),
            "urgency": str(self.urgency),
            "message": self.message,
        }
