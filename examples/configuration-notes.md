# Example configuration (placeholders only)

gHAndalf is configured entirely through the Home Assistant UI — there is **no YAML
to copy**. This file just shows the *kind* of entities each role expects, using
placeholder IDs. Map your own real entities in **Settings → Devices & Services →
gHAndalf → Configure**.

| gHAndalf role | Example entity (placeholder) | Notes |
|---|---|---|
| PV production power | `sensor.example_pv_power` | required, `device_class: power` |
| Household consumption power | `sensor.example_consumption_power` | required, `device_class: power` |
| Grid import power | `sensor.example_grid_import_power` | optional |
| Grid export power | `sensor.example_grid_export_power` | optional |
| Battery state of charge | `sensor.example_battery_soc` | optional, `device_class: battery` |

Tunables (also in the UI, all with sane defaults):

| Tunable | Default | Range |
|---|---|---|
| Scan interval | 30 s | 10–600 s |
| Solar-surplus threshold | 1000 W | 0–20000 W |

> Never commit your real entity IDs or any secrets to a public repo. Your mapping
> lives in your own Home Assistant instance.
