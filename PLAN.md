# Plan

## Goal
A reliable Home Assistant integration for the user's Rain Bird ESP-ME3, more
robust than the stock local integration (which can't reach it) and the
`rainbird_iq4` HACS integration (fragile auth).

## Key finding
MITM capture proved the device is **IQ4 cloud / AWS-MQTT only** — no local API.
So we build a self-hosted **IQ4 cloud** client, not a LAN-only one.

## Decisions (locked)
- Talk to IQ4 directly: `iq4server.rainbird.com` REST + AWS AppSync realtime.
- Auth via the app's `refresh_token` grant (Basic client auth), not HTML scraping.
- One-source client under `custom_components/rainbird_ha/client/` (no HA deps).

## Status
- [x] IQ4 REST client (auth, satellites, stations, run status, start/stop, rain delay) — **validated live** (reads).
- [x] AppSync realtime stream — **validated live** (connect + subscribe; needs `Bearer` prefix).
- [x] HA integration MVP: config flow, coordinator (poll + stream), switch/binary_sensor/sensor, options.
- [x] Onboarding login: OIDC **authorization-code + PKCE** (email/password) — **validated live**; mints an independent lineage, phone app unaffected. (ROPC `grant_type=password` is disabled server-side.)
- [x] Live control (start/stop zone 1) — **validated live**: StartStations→204, AdvanceStations stops, realtime confirms.
- [x] Stream event schema decoded: SK=`Station<terminal>`, Data=`{state:1 running / -1 stopped, remainSec}`. Coordinator maps terminal→station id. (REST `run-status.status` stays `-` even when running — unreliable; the stream is authoritative.)
- [x] Rain-delay control (PATCH `Satellite/v2/UpdateBatches`, days→.NET ticks) + Number entity — **validated live** (set 1, read back 1, cleared to 0). GetSatelliteList `rainDelay` is in days.
- [x] Per-zone "run time" Number entities (RestoreNumber, EntityCategory.CONFIG, 1–240 min, default 10) — switch-on uses each zone's value. **Verified end-to-end in HA** (set zone 1 to 1 min, switch on → time_remaining 46s not 600s). Duration is device-enforced, so zones auto-stop even if HA dies.
- [x] Deployed and running in the user's HA (HA OS, entry 01KWTT8XZNWXRJ082KZHDRP4CP). Blocking-I/O warnings fixed via async token persistence.
- [ ] Cold-start: active zone unknown until the next stream event (stream is change-driven). Minor; consider a startup state query if a reliable field is found.

## Open inputs needed from user
- Install in Home Assistant and report results (or ask me to add rain-delay control first).

## Protocol reference (verified)
- Token: `POST /coreidentityserver/connect/token`, HTTP Basic client auth
  (client_id:client_secret — user-supplied, captured via tools/), form
  `grant_type=refresh_token`. Rotates refresh token.
- Start: `POST /coreapi/api/ManualOps/StartStations` `{stationIds, seconds, isGroupStart:false}` → 204.
- Stop: `POST /coreapi/api/ManualOps/AdvanceStations?isProgramIndex=true` `[{programId:-1, stationId}]`.
- State: `Station/GetStationListForSatellite`, `Satellite/isConnected`, `ProgramStep/GetRunStationStatusForSatellite`.
- Realtime: `wss://…appsync-realtime-api…/graphql?header=<b64{host:api-host,Authorization:"Bearer "+tok}>&payload=e30=`, sub `onUpdateDeviceStateTable(PK=deviceUUID)`.
