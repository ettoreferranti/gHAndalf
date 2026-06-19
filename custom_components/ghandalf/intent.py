"""Assist intent: answer 'how long for the washing machine?' from tracked state.

Registers a custom intent handler; the matching spoken sentences live in
``custom_sentences/en/ghandalf.yaml`` (shipped alongside, copied into the HA
config dir) so the default Assist agent routes those phrases here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent

from .const import DOMAIN

INTENT_LAUNDRY_STATUS = "GHandalfLaundryStatus"


def _appliance_phrase(appliance: dict[str, Any]) -> str:
    """One spoken clause describing an appliance's current state."""
    name = appliance.get("name", "the appliance")
    if appliance.get("awaiting_unload"):
        mins = appliance.get("finished_minutes_ago")
        ago = f"{mins} minutes ago" if mins else "a moment ago"
        return (
            f"{name} finished {ago} and hasn't been unloaded yet — "
            "time to take the laundry out"
        )
    if appliance.get("running"):
        mins = appliance.get("minutes_left")
        if mins is not None:
            return f"{name} has about {mins} minutes left"
        return f"{name} is running"
    return f"{name} is off"


def _appliances(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Current appliance snapshot from the gHAndalf coordinator (if set up)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None and coordinator.data is not None:
            return coordinator.data.get("appliances", [])
    return []


class LaundryStatusIntentHandler(intent.IntentHandler):
    """Speaks the status of every tracked appliance."""

    intent_type = INTENT_LAUNDRY_STATUS
    description = "Status of tracked appliances (washing machine, dryer, dishwasher)."

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        appliances = _appliances(intent_obj.hass)
        if not appliances:
            response.async_set_speech("No appliances are set up in gHAndalf yet.")
            return response
        clauses = [_appliance_phrase(a) for a in appliances]
        speech = ". ".join(c[0].upper() + c[1:] for c in clauses) + "."
        response.async_set_speech(speech)
        return response


@callback
def async_register_intents(hass: HomeAssistant) -> None:
    """Register gHAndalf's Assist intents (idempotent across reloads)."""
    intent.async_register(hass, LaundryStatusIntentHandler())
