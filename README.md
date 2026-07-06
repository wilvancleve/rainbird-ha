# Rain Bird (self-hosted IQ4) — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/wilvancleve/rainbird-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/wilvancleve/rainbird-ha/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant integration for Rain Bird controllers that live on the **IQ4
cloud platform** — for example an **ESP-ME3 with an LNK2 module in MQTT mode**.
These controllers expose **no local API**, so Home Assistant's built-in Rain
Bird integration (which speaks the legacy local protocol) can't reach them and
leaves the device *unavailable*.

This integration talks to the IQ4 cloud the same way the official **Rain Bird
2.0** app does, so it just works where the local integration can't.

> **Not affiliated with, or endorsed by, Rain Bird.** This project uses the
> mobile app's private API to interoperate with hardware you own. It may stop
> working if Rain Bird changes their app or backend. See [Disclaimer](#disclaimer).

## Why this vs. other options

| | Built-in `rainbird` | `rainbird_iq4` | **this** |
|---|---|---|---|
| Works with cloud/MQTT ESP-ME3 | ❌ (local only) | ✅ | ✅ |
| Auth method | local passcode | scrapes web login every ~2 h (WAF-prone) | app's **refresh-token** grant |
| Realtime updates | — | polling | **AppSync push** |
| Schedule read/write | ❌ | partial | **full CRUD** |
| Bundled dashboard card | ❌ | ✅ | ✅ (auto-registered) |

The auth difference is the important one: instead of re-driving the fragile HTML
sign-in page (which AWS WAF frequently blocks), this uses the app's OAuth
`refresh_token` flow — one durable, self-rotating session that survives restarts.

## Features

- **Zones** — a switch per station; each has its own **run-time** number, and a
  switch-on starts that zone for its configured minutes (enforced by the
  controller, so a zone can never be left running).
- **Realtime status** — active zone, seconds remaining, and connectivity, pushed
  over the same AWS AppSync WebSocket the app uses.
- **Rain delay** — a days number entity.
- **Controller power** — a switch that turns the whole controller On (Auto)/Off.
- **Schedule** — a sensor per program showing days, start times, per-zone
  minutes, and seasonal adjust, plus [services](#services) to create, edit, and
  clear programs.
- **Dashboard card** (`custom:rainbird-ha-card`) — bundled and
  auto-registered: zone tiles with a live-animating progress bar, per-zone
  duration steppers, a schedule panel, rain-delay control, and a
  confirm-guarded power button.

## Requirements

- Home Assistant **2024.7** or newer.
- A Rain Bird controller managed through the **Rain Bird 2.0 app** (IQ4 backend).
- Your Rain Bird 2.0 app **email and password**.
- Your **own OAuth `client_id` and `client_secret`**, captured from the app —
  see [Getting your OAuth client credentials](#getting-your-oauth-client-credentials).

> This project does **not** ship Rain Bird's app credentials. You capture your
> own from the app you already use; the one-time proxy capture takes a couple of
> minutes.

## Getting your OAuth client credentials

The `client_id`/`client_secret` are needed to authenticate. They aren't shipped
here, so capture your own with the bundled proxy (details in
[`tools/README.md`](tools/README.md)):

1. Install [mitmproxy](https://mitmproxy.org/) and run `./tools/run_proxy.sh`.
2. Point your phone's Wi-Fi proxy at it, trust the CA (http://mitm.it), and sign
   in to the Rain Bird 2.0 app.
3. The proxy prints and saves your `client_id`/`client_secret` (decoded from the
   token request). Keep them handy for setup below.

## Installation

### HACS (recommended)

1. HACS → **⋮** → **Custom repositories** → add
   `https://github.com/wilvancleve/rainbird-ha` with category **Integration**.
2. Install **Rain Bird (self-hosted IQ4)** and **restart** Home Assistant.
3. **Settings → Devices & Services → Add Integration →** search
   *Rain Bird (self-hosted IQ4)* and enter your app email + password and the
   `client_id`/`client_secret` you captured.

### Manual

Copy `custom_components/rainbird_ha` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

The config flow signs in with the app's OAuth **authorization-code + PKCE** flow
(using the `client_id`/`client_secret` you provide) and stores a refresh token.
Home Assistant gets **its own session**, independent of your phone — the two
coexist and won't sign each other out. If you have more than one controller,
you'll be asked to pick one (add the integration again for others).

Entities are created per controller: `switch.<name>_station_00X`,
`number.<name>_station_00X_run_time`, `number.<name>_rain_delay`,
`switch.<name>_controller`, `binary_sensor.<name>_connectivity`,
`sensor.<name>_active_zone`, `sensor.<name>_time_remaining`, and
`sensor.<name>_program_a..d`.

## Dashboard card

The card is bundled and auto-registered on install — just add it to a dashboard:

```yaml
type: custom:rainbird-ha-card
# title: Irrigation           # optional
# prefix: my_controller_name  # optional; only if you run more than one controller
```

It auto-discovers the controller's entities. (If your browser shows a stale
version after an update, hard-refresh once.)

## Services

All services target a program by its numeric `program_id` (shown in each Program
sensor's attributes).

| Service | Purpose |
|---|---|
| `rainbird_ha.set_program_days` | days a program runs (`1111111` daily … `0000000` off) |
| `rainbird_ha.add_start_time` / `delete_start_time` | add / remove a daily start time |
| `rainbird_ha.set_program_stations` | set a program's zones + minutes |
| `rainbird_ha.set_seasonal_adjust` | seasonal (water-budget) % |
| `rainbird_ha.rename_program` | rename a program |
| `rainbird_ha.clear_program` | empty a program (steps + start times + days off) |

> On an ESP-ME3 the four program slots (A–D) are fixed — "create a schedule"
> means populating an empty slot, and `clear_program` empties one.

## About the OAuth client credentials

This project intentionally does **not** distribute Rain Bird's app
`client_id`/`client_secret` — you supply your own, captured from the app you use
(see [Getting your OAuth client credentials](#getting-your-oauth-client-credentials)).
If Rain Bird ever rotates them, just re-capture with the bundled proxy and update
the integration's credentials.

> Note: static extraction from the app package can't recover these — the app
> supplies them to its OAuth library from a non-literal source. Capturing the
> live token request (what `tools/` does) is the reliable method.

## Troubleshooting

- **Unavailable / auth errors after a while** — Rain Bird may have invalidated
  the session; remove and re-add the integration to sign in again.
- **Transient `DNS`/timeout errors in the log** — the IQ4 cloud briefly
  unreachable; the integration retries with backoff and recovers on its own.
- **Card not updating smoothly / stale** — hard-refresh the browser after an
  upgrade to clear the cached card.

## Disclaimer

This is an independent, community project. It is **not affiliated with,
authorized, or supported by Rain Bird**. It communicates with Rain Bird's cloud
using the same private API as the official app, for the purpose of
**interoperability with irrigation hardware you own**. It does not bypass any
subscription or entitlement — the server still enforces your account's
permissions. It may stop working at any time if Rain Bird changes their app or
services. Use at your own risk. "Rain Bird" and "ESP-ME3" are trademarks of
their respective owner.

## License

[MIT](LICENSE)
