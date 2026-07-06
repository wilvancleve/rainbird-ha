"""Coordinator: merges REST polling with the AppSync realtime stream."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEFAULT_MINUTES, DEFAULT_MINUTES, DOMAIN, SCAN_INTERVAL_SECONDS
from .client.iq4 import IQ4Auth, IQ4Client, IQ4Error, Station
from .client.stream import IQ4Stream, StreamEvent

_LOGGER = logging.getLogger(__name__)


@dataclass
class ControllerData:
    """Merged view of a controller's state."""

    connected: bool = False
    power_on: bool = True
    stations: list[Station] = field(default_factory=list)
    active_station_id: int | None = None
    remain_seconds: int | None = None
    rain_delay: int | None = None
    programs: list[dict] = field(default_factory=list)
    # Local rain/moisture sensor: True=active/sensing, False=inactive, None=no sensor.
    sensor_active: bool | None = None
    sensor_name: str | None = None


TICKS_PER_MINUTE = 60 * 10_000_000
_DAY_LETTERS = ["Su", "M", "Tu", "W", "Th", "F", "Sa"]


def _days_summary(mask: str) -> str:
    """'1111111' -> 'Daily', '0000000' -> 'Off', else e.g. 'M,W,F'."""
    if not mask or len(mask) != 7 or "1" not in mask:
        return "Off"
    if mask == "1111111":
        return "Daily"
    return ",".join(d for d, on in zip(_DAY_LETTERS, mask) if on == "1")


def _hhmm(start: dict) -> str:
    val = start.get("dateTimeLocal") or start.get("dateTime") or ""
    return val[11:16] if len(val) >= 16 else val  # 'YYYY-MM-DDTHH:MM:...' -> 'HH:MM'


class RainbirdCoordinator(DataUpdateCoordinator[ControllerData]):
    """Polls the IQ4 REST API and consumes realtime AppSync events."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        satellite_id: int,
        device_uuid: str,
        auth: IQ4Auth,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {satellite_id}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.config_entry = entry
        self.satellite_id = satellite_id
        self.device_uuid = device_uuid
        self.auth = auth
        self.client = IQ4Client(auth)
        self._stream = IQ4Stream(auth, device_uuid)
        self._stream_task: asyncio.Task | None = None
        self._data = ControllerData()
        # Per-zone run duration (minutes) used when a zone switch is turned on;
        # maintained by the per-zone "run time" number entities.
        self.zone_minutes: dict[int, int] = {}

    def zone_run_minutes(self, station_id: int) -> int:
        """Configured run time (minutes) for a zone switch-on."""
        default = self.config_entry.options.get(CONF_DEFAULT_MINUTES, DEFAULT_MINUTES)
        return self.zone_minutes.get(station_id, default)

    async def _async_update_data(self) -> ControllerData:
        try:
            connected = await self.client.is_connected(self.satellite_id)
            stations = await self.client.get_stations(self.satellite_id)
            sat = next((s for s in await self.client.get_satellites()
                        if s.id == self.satellite_id), None)
            programs = await self._build_programs(stations)
            sensors = await self.client.get_sensors(self.satellite_id)
        except IQ4Error as err:
            raise UpdateFailed(f"Error polling IQ4: {err}") from err
        self._data.connected = connected
        self._data.stations = stations
        raw = sat.raw if sat else {}
        self._data.rain_delay = int(raw.get("rainDelay") or 0)
        self._data.power_on = not bool(raw.get("isShutdown"))
        self._data.programs = programs
        # Local rain/moisture sensor (the controller's on-board sensor input).
        local = next((s for s in sensors
                      if s.get("isLocal") and "onOffState" in s), None)
        if local:
            self._data.sensor_active = bool(local.get("onOffState"))
            self._data.sensor_name = local.get("name") or "Sensor"
        else:
            self._data.sensor_active = None
        # Active-station truth comes from the realtime stream; keep whatever it set.
        return self._data

    async def _build_programs(self, stations: list[Station]) -> list[dict]:
        """Fetch each program with its start times and station steps, enriched."""
        term = {s.id: s.terminal for s in stations}
        out: list[dict] = []
        for p in await self.client.get_programs(self.satellite_id):
            pid = p["id"]
            steps = await self.client.get_program_steps(pid)
            starts = await self.client.get_start_times(pid)
            mask = p.get("weekDays") or "0000000"
            out.append({
                "id": pid,
                "name": p.get("name", ""),
                "short": p.get("shortName", ""),
                "days_mask": mask,
                "days": _days_summary(mask),
                "seasonal_adjust": p.get("programAdjust"),
                "runs": "1" in mask and bool(steps) and bool(starts),
                "start_times": [
                    {"id": st["id"], "time": _hhmm(st)} for st in starts
                ],
                "stations": [
                    {
                        "step_id": s["id"],
                        "station_id": s["stationId"],
                        "terminal": term.get(s["stationId"]),
                        "minutes": round((s.get("runTimeLong") or 0) / TICKS_PER_MINUTE),
                    }
                    for s in steps
                ],
            })
        return out

    def program(self, program_id: int) -> dict | None:
        return next((p for p in self._data.programs if p["id"] == program_id), None)

    def _terminal_to_id(self, terminal: int) -> int | None:
        for s in self._data.stations:
            if s.terminal == terminal:
                return s.id
        return None

    def _on_event(self, ev: StreamEvent) -> None:
        # Per-station events: SK terminal + running flag drive the active zone.
        if ev.terminal is not None and ev.running is not None:
            station_id = self._terminal_to_id(ev.terminal)
            if ev.running:
                self._data.active_station_id = station_id
                self._data.remain_seconds = ev.remain_seconds
            elif self._data.active_station_id == station_id:
                self._data.active_station_id = None
                self._data.remain_seconds = None
        if ev.rain_delay is not None:
            self._data.rain_delay = ev.rain_delay
        _LOGGER.debug("Realtime event sk=%s running=%s -> active=%s remain=%s",
                      ev.sk, ev.running, self._data.active_station_id,
                      self._data.remain_seconds)
        self.async_set_updated_data(self._data)

    async def _stream_loop(self) -> None:
        try:
            async for ev in self._stream.listen():
                self._on_event(ev)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Realtime stream stopped: %s", err)

    async def async_start_stream(self) -> None:
        if self._stream_task is None:
            self._stream_task = self.hass.async_create_background_task(
                self._stream_loop(), f"{DOMAIN}_stream_{self.satellite_id}"
            )

    async def async_stop_stream(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None
