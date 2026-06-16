# gHAndalf

> Personal Assistant for your Home Assistant — a coach that mentors you toward
> home-management enlightenment: save energy, maximise solar self-consumption,
> keep the air fresh. *You shall not pass… that 4 kW grid import at peak tariff.*

**Status: early scaffolding.** This first slice installs as a Home Assistant
custom component, lets you map your energy entities in the UI, reads their live
state, and exposes a few derived/diagnostic sensors so you can confirm it works.
The coaching nudges and digest come next — see [`REQUIREMENTS.md`](REQUIREMENTS.md).

## What works today

- A config flow to map your core energy entities (PV, consumption, optional grid
  import/export and battery SoC).
- A coordinator that reads those entities' **live** state on a configurable interval.
- Three sensors:
  - **Solar surplus** (W) — PV production minus household consumption.
  - **Net grid power** (W) — positive = importing, negative = exporting.
  - **Status** — `ok` / `degraded`, listing any mapped-but-unavailable entities.
- An options flow to re-map entities and retune values — **nothing is hardcoded**.

## Design principles

gHAndalf is **HA-native and source-agnostic** (it reads the live state machine,
never a vendor API), the LLM layer is **optional** (rules do the work), and it is
**private by construction** — it opens no inbound network surface, sends no
telemetry, and keeps no secrets or personal data in this repo. Full rationale and
roadmap in [`REQUIREMENTS.md`](REQUIREMENTS.md).

## Installation (manual, for now)

1. Copy `custom_components/ghandalf/` into your HA config's `custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → + Add Integration → gHAndalf.**
4. Map at least PV production and household consumption power. Done.

## Development

```bash
pip install -r requirements_test.txt
ruff check . && ruff format --check .
pytest --cov --cov-report=term-missing
```

Mutation testing (on the pure-logic helpers):

```bash
mutmut run        # mutate helpers.py and re-run the unit tests
mutmut results    # any survivors mean a test gap to close
```

## License

MIT
