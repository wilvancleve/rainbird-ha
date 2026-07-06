# Rain Bird (self-hosted IQ4)

Home Assistant integration for Rain Bird controllers on the **IQ4** cloud
platform (e.g. an ESP-ME3 with an LNK2 module in MQTT mode) — the ones that have
**no local API** and can't be reached by the built-in Rain Bird integration.

- **Robust auth** — uses the app's own OAuth refresh-token flow (no fragile
  HTML-login scraping, no WAF pain), so it stays connected across restarts.
- **Realtime** — consumes the same AWS AppSync stream the app uses, so zone
  state and countdowns update instantly.
- **Zone control** — a switch per zone, each with its own configurable run time.
- **Schedule** — read every program's days/start-times/zone-minutes, plus
  services to create, edit, and clear programs.
- **Controller power** and **rain delay** controls.
- **Bundled dashboard card** (auto-registered) with a live progress bar,
  schedule panel, and a confirm-guarded power button.

Sign in with your Rain Bird 2.0 app email + password — Home Assistant gets its
own session and won't sign your phone out.

> Not affiliated with Rain Bird. Uses the mobile app's private API for
> interoperability with hardware you own; it may break if Rain Bird changes
> their app.
