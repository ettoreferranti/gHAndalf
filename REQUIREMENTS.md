# gHAndalf — Requirements (v1 draft)

> A Home Assistant custom component that **coaches** the household into better habits:
> save energy, maximise solar self-consumption, keep the air fresh, ventilate smartly.
> A wizard for your home. *You shall not pass… that 4 kW grid import at peak tariff.*

Status: requirements draft. Nothing implemented yet.

> **Note on configuration:** every entity ID and threshold in this document is illustrative.
> gHAndalf hardcodes nothing — all entities and tunables are set through the Home Assistant
> config/options UI. Your own entity mapping lives in your HA instance, never in this repo.

---

## 1. Vision & scope

gHAndalf observes the home through Home Assistant and produces **timely, specific, non-annoying
coaching** — proactive nudges in the moment, plus a reflective daily/weekly digest. It is a
*coach*, not (yet) a controller: v1 only advises; **it never actuates anything**.

**v1 pillars (only these two):**
1. **Solar self-consumption & energy** — shift flexible loads into PV surplus / cheap-tariff
   windows, avoid expensive grid import, respect the battery and tomorrow's forecast.
2. **Air quality & comfort** — CO₂ / PM2.5 / humidity → smart ventilation nudges, cross-checked
   against outdoor conditions and room occupancy.

Explicitly **out of scope for v1** (see §12): any actuation, actionable notification buttons,
multi-person routing, and pillars beyond the two above (appliance lifecycle, heating optimisation,
gamification leaderboards, etc. — noted as future ideas).

---

## 2. Principles (the non-negotiables)

1. **HA-native and source-agnostic.** gHAndalf reads the **live HA state machine** via mapped
   entity IDs — never a vendor API. It must work for any HA install, regardless of which brands or
   integrations provide the underlying sensors.
2. **The LLM is optional.** Deterministic rules do the detection and the heavy lifting. The LLM is
   a thin, swappable layer for *phrasing*, *prioritising*, and the *digest narrative*. With the LLM
   off (or unreachable), gHAndalf still coaches using templated text. *Don't reach for an LLM to
   solve a problem you don't have.*
3. **Anti-alert-fatigue is a feature, not an afterthought.** A nudge budget, quiet hours, cooldowns,
   dedupe, and presence-gating are first-class. A coach you mute has failed.
4. **Advice-only in v1.** Actuation is deliberately deferred (§12).
5. **Specific, timed, actionable.** Every nudge says *what*, *why now*, and *what to do*.
6. **Private by construction.** No inbound network surface, no telemetry, no secrets in the repo
   (§ security, below and in the build docs).

---

## 3. Architecture

Runtime: a **Home Assistant custom component** (`custom_components/ghandalf/`) with a config flow,
an options flow, and a coordinator.

```
   Mapped HA entities (solar, CO2, temp, windows, presence, tariff, forecast…)
                              │  (live state, via hass.states)
                       ┌──────▼───────┐
                       │ Coordinator  │  samples mapped entities on tick + state-change events
                       └──────┬───────┘
                       ┌──────▼───────┐
                       │ Rule engine  │  pure functions → AdviceCandidate[]
                       └──────┬───────┘   (category, urgency, message_template, data, cooldown)
                       ┌──────▼───────┐
                       │  Nudge gate  │  quiet hours + per-category budget + dedupe + presence
                       └───┬──────┬───┘
              ┌────────────▼─┐  ┌─▼──────────────┐
              │ Proactive    │  │ Digest builder │ (scheduled: daily + weekly)
              │ notifier     │  └─┬──────────────┘
              └───────┬──────┘    │
                      └─────┬──────┘
              ┌─────────────▼─────────────┐
              │ Narrator (OPTIONAL LLM)   │  HA conversation agent; templated fallback
              └─────────────┬─────────────┘
                            ▼
                     User's mobile app
                            │
                  ┌─────────▼─────────┐
                  │ Habit store       │  nudge log + weekly aggregate metrics (light loop)
                  └───────────────────┘
```

### 3.1 LLM narration seam

- Backend = **any HA-registered conversation agent**, selected in the options flow. A **local LLM**
  (e.g. an Ollama agent on the LAN) keeps token cost at zero while iterating; swap to a cloud agent
  later via dropdown. Near-zero custom LLM plumbing.
- Interface is narrow: `narrate(candidates) -> str` and `narrate_digest(metrics, events) -> str`.
- **Mandatory templated fallback** when no agent is configured or the agent is unreachable. The LLM
  only ever *rephrases/prioritises* deterministic content — it never invents facts or decides actions.

---

## 4. Configuration — entity-role mapping

The component is configured by mapping **roles** to entity IDs through the HA UI. This is what keeps
it source-agnostic. Roles for v1:

| Role | Required | Notes |
|---|---|---|
| `pv_production_power` (W) | ✓ | |
| `household_consumption_power` (W) | ✓ | |
| `grid_import_power` / `grid_export_power` (W) | ✓ | or a single signed grid-power entity |
| `battery_soc` (%) / `battery_charge_power` / `battery_discharge_power` | optional | enables battery-aware logic |
| `tariff_current_price` / `tariff_next_change` / `tariff_schedule` | optional | see §5 |
| `solar_forecast_peak_today` / `_tomorrow` | optional | from a solar-forecast integration |
| `co2[]` (ppm, per room) | ✓ (pillar 2) | list of (room, entity) |
| `pm25[]` (µg/m³, per room) | optional | |
| `indoor_temp[]` / `indoor_humidity[]` (per room) | ✓ (pillar 2) | |
| `outdoor_temp` / `outdoor_humidity` / `outdoor_dew_point` | ✓ (pillar 2) | from a weather/outdoor-station integration |
| `window[]` (binary, per room) | optional | enables "heating with window open" + "already venting" |
| `occupancy[]` (binary motion, per room) / `persons[]` | optional | presence-gating |
| `notify_service` | ✓ | the mobile-app notify target |

A per-install mapping is created entirely in the user's HA instance. **No real entity mapping is
committed to this repo** — only a sanitized `examples/` config with placeholder IDs.

---

## 5. Tariff abstraction (future-proofed)

The price source is modelled generically so the same rules work across tariff structures:

- A **simple two-rate** tariff (e.g. high/low, day/night).
- A **dynamic per-slot** tariff (e.g. 15-minute slots published ~a day ahead).

Model a `TariffSchedule` providing: `price_now`, `next_change_at`, and an ordered list of upcoming
`(start, end, price)` slots (length 1–2 for two-rate, up to ~96 for 15-minute day-ahead). All rules
consume this interface, so the same logic works regardless of tariff granularity. Include
`export_price` (feed-in compensation) where available, so "is exporting worth less than
self-consuming right now?" is answerable.

---

## 6. Pillar 1 rule catalog — solar & energy

**Optimization objective: blended** — prefer PV surplus, fall back to cheap-tariff windows when
there's no surplus, weighted by battery SoC and tomorrow's forecast. Not pure-solar, not pure-cost.

Candidate rules (all thresholds are defaults, configurable in the UI):

| Rule | Fires when | Nudge (advice-only) |
|---|---|---|
| **Surplus available** | export > ~1 kW (or PV − consumption > a flexible-load size) **and** battery SoC high | "~X kW of free solar right now — good time to run a flexible load." |
| **Don't import at peak** | grid import > threshold **and** tariff in an expensive slot **and** a cheaper slot within N h | "You're importing at {price}; a cheaper slot starts {time}. Defer what you can." |
| **Battery-aware deferral** | low SoC **and** sunny forecast tomorrow | "Battery's low but tomorrow's sunny — no need to grid-charge tonight." |
| **Exporting cheap** | exporting **and** feed-in compensation < current import price | "You're exporting at {comp} but buying at {price} later — shift usage into now." |
| **Forecast heads-up** (digest-ish) | morning | "Peak sun ~{peak_time}, expected good/poor production — plan big loads around it." |
| **Phantom/standby** (stretch) | overnight baseline consumption unusually high | "Baseline draw is {W} overnight — something's on that needn't be." |

Each candidate carries: category, urgency, cooldown, and the structured data the narrator/templater
needs. **No rule actuates** — they only inform.

---

## 7. Pillar 2 rule catalog — air quality & comfort

CO₂ bands (default, configurable): `<800` fresh · `800–1000` ok · `1000–1400` act · `>1400` urgent.

| Rule | Fires when | Nudge |
|---|---|---|
| **Ventilate (CO₂)** | room CO₂ > act band **and** room occupied **and** window closed **and** outdoor air is better (temp/PM acceptable) | "CO₂ in {room} is {ppm} — crack the window ~10 min; it's {outdoor}° outside." |
| **Stop venting** | window open **and** CO₂ back to fresh (or outdoor worse) | "{room} air is fresh again — you can close the window." |
| **Heating with window open** | a room's window open > N min **and** heating active for that zone | "Window open in {room} while heating — close it or pause the zone." |
| **Humidity comfort** | indoor humidity outside 40–60 % sustained | dry: "Air's dry ({rh}%) — …"; damp: "{room} is humid ({rh}%) — ventilate / check for condensation." |
| **PM2.5 spike** | PM2.5 > threshold | "Particulates up in {room} ({µg}) — keep windows shut; let the purifier handle it." |
| **Don't vent now** (suppression, not a nudge) | outdoor worse than indoor (hot/humid/high PM) | suppresses the ventilate rule rather than nagging |

Outdoor cross-check uses outdoor temp / humidity / **dew point** (to avoid condensation advice) and
outdoor PM where available. Presence-gating uses per-room motion + `person` home/away.

---

## 8. Nudge gate (anti-alert-fatigue)

- **Quiet hours** (default 22:00–07:00): no proactive nudges in v1 (no override).
- **Per-category budget**: ≤ 3 nudges/category/day; global daily cap 8.
- **Cooldown** per rule instance (don't re-nudge the same room's CO₂ every cycle): 60 min default.
- **Dedupe / debounce**: a candidate must persist ~5 min before firing (avoid transient spikes).
- **Presence-gating**: don't nudge an empty house or an empty room.
- **Hysteresis**: separate on/off thresholds so a value hovering at the line doesn't flap.

---

## 9. Digest (daily + weekly)

Scheduled, reflective, low-pressure. Built from the habit store (§10) + recorder history.

- **Daily** (default 07:30): yesterday's solar self-consumption %, grid import cost, CO₂ "stuffy
  minutes" per room, notable events, today's solar forecast + 1–2 concrete suggestions.
- **Weekly** (default Monday 08:00): trends vs last week (self-consumption %, cost, ventilation
  responsiveness), what went well, one focused thing to try next week.
- Narrated by the LLM when available; templated otherwise.

---

## 10. Habit store (light closed-loop)

Persist (HA Store / small SQLite):
- **Nudge log**: every candidate fired (category, time, payload).
- **Weekly aggregate metrics**: solar self-consumption %, grid import kWh + cost, CO₂ minutes over
  threshold per room, ventilation events.

v1 does **not** attribute cause ("you acted → it improved") — that's a later upgrade. It just logs
and aggregates so the digest can show real trends.

---

## 11. Notifications

- Channel: the user's **mobile app** (`notify_service` role). Advice-only text.
- Single audience in v1. No per-person / presence routing yet.

---

## 12. Non-goals / deferred (v2+)

v1 stays advice-only by choice. Many homes already expose writeable controls; gHAndalf simply
doesn't touch them yet. Deferred:

- **Actionable notifications** (one-tap buttons calling low-risk services).
- **Direct control**: smart washer/dryer with delayed-start, an air-purifier fan, heat-pump climate
  entities, lights/switches. Caveat to design around: some appliance integrations gate remote
  control behind the appliance being physically armed.
- **Pillar expansion**: appliance lifecycle ("done → unload"), heating optimisation, gamification.
- **Per-person / presence-aware routing**; on-demand "ask the coach" chat; dashboard scorecard.

---

## 13. Security & privacy requirements

- The component runs **inside** HA and exposes **no inbound network surface** — no ports, no
  webhooks. It only reads HA state and calls a `notify` service.
- Any optional LLM backend is reached **outbound on the LAN** (local agent) or via HA's own cloud
  integration. A local LLM endpoint must **never** be exposed to the public internet.
- Secrets (e.g. a future cloud-LLM key) live only in the **HA config entry (encrypted storage)** —
  never in YAML, logs, or this repo.
- **No personal data in the repo**: no real entity IDs, no home IPs, no credentials. Examples use
  placeholders; per-install mappings stay in the user's HA.
- Logs must not leak sensitive values. Dependencies are **minimal and pinned**. No telemetry.
- All UI-configurable values are **bounds-validated** (no negative thresholds, sane ranges).

---

## 14. Testing requirements

- `pytest` + `pytest-homeassistant-custom-component` (+ `aioresponses` for any HTTP).
- **≥ 90 %** coverage on the logic core (rule engine, tariff abstraction, nudge gate).
- **Mutation testing** (`mutmut`) on the pure-logic modules — deterministic and ideal targets;
  surviving mutants drive test hardening.
- CI (GitHub Actions): `ruff` lint + tests on every PR; mutation run on a manual/periodic trigger.

---

## 15. Build order (suggested)

1. Scaffolding: component skeleton, config/options flow, coordinator reading mapped entities.
2. Rule engine + nudge gate + templated notifier (no LLM) — prove the deterministic core.
3. Habit store + daily/weekly digest (templated).
4. LLM narrator seam against a local conversation agent.
5. Tune thresholds/budgets against real data.
