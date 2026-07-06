"""Schedule CRUD services for rainbird_ha.

All services target a program by its numeric ``program_id`` (visible in each
Program sensor's attributes). They route to whichever controller owns that
program, perform the write, and refresh so the display updates.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .coordinator import RainbirdCoordinator

_DAYS_MASK = vol.All(cv.string, vol.Match(r"^[01]{7}$"))

SERVICES = (
    "set_program_days", "set_seasonal_adjust", "rename_program",
    "add_start_time", "delete_start_time", "set_program_stations", "clear_program",
)


def _coordinator_for(hass: HomeAssistant, program_id: int) -> RainbirdCoordinator:
    for coord in hass.data.get(DOMAIN, {}).values():
        if isinstance(coord, RainbirdCoordinator) and coord.program(program_id):
            return coord
    raise HomeAssistantError(f"No Rain Bird program with id {program_id}")


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "add_start_time"):
        return

    async def set_program_days(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.set_program_days(call.data["program_id"], call.data["days"])
        await c.async_request_refresh()

    async def set_seasonal_adjust(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.update_program(call.data["program_id"], {
            "programAdjust": call.data["percent"], "useProgramAdjust": True,
        })
        await c.async_request_refresh()

    async def rename_program(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.update_program(call.data["program_id"], {"name": call.data["name"]})
        await c.async_request_refresh()

    async def add_start_time(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.add_start_time(
            call.data["program_id"], call.data["time"].strftime("%H:%M"))
        await c.async_request_refresh()

    async def delete_start_time(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.delete_start_time(
            call.data["program_id"], call.data["start_time_id"])
        await c.async_request_refresh()

    async def set_program_stations(call: ServiceCall) -> None:
        """Replace a program's station steps. stations: [{terminal, minutes}, ...]."""
        pid = call.data["program_id"]
        c = _coordinator_for(hass, pid)
        term_to_id = {s.terminal: s.id for s in c.data.stations}
        steps = []
        for item in call.data["stations"]:
            sid = term_to_id.get(item["terminal"])
            if sid is None:
                raise HomeAssistantError(f"No station on terminal {item['terminal']}")
            steps.append((sid, item["minutes"]))
        existing = await c.client.get_program_steps(pid)
        if existing:
            await c.client.delete_program_steps([s["id"] for s in existing])
        if steps:
            await c.client.create_program_steps(pid, steps)
        await c.async_request_refresh()

    async def clear_program(call: ServiceCall) -> None:
        c = _coordinator_for(hass, call.data["program_id"])
        await c.client.clear_program(call.data["program_id"])
        await c.async_request_refresh()

    pid = {vol.Required("program_id"): cv.positive_int}
    reg = hass.services.async_register
    reg(DOMAIN, "set_program_days", set_program_days,
        schema=vol.Schema({**pid, vol.Required("days"): _DAYS_MASK}))
    reg(DOMAIN, "set_seasonal_adjust", set_seasonal_adjust,
        schema=vol.Schema({**pid, vol.Required("percent"):
                           vol.All(vol.Coerce(int), vol.Range(min=0, max=300))}))
    reg(DOMAIN, "rename_program", rename_program,
        schema=vol.Schema({**pid, vol.Required("name"): cv.string}))
    reg(DOMAIN, "add_start_time", add_start_time,
        schema=vol.Schema({**pid, vol.Required("time"): cv.time}))
    reg(DOMAIN, "delete_start_time", delete_start_time,
        schema=vol.Schema({**pid, vol.Required("start_time_id"): cv.positive_int}))
    reg(DOMAIN, "set_program_stations", set_program_stations,
        schema=vol.Schema({**pid, vol.Required("stations"): vol.All(
            cv.ensure_list, [vol.Schema({
                vol.Required("terminal"): cv.positive_int,
                vol.Required("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=240)),
            })])}))
    reg(DOMAIN, "clear_program", clear_program, schema=vol.Schema(pid))


def async_unload_services(hass: HomeAssistant) -> None:
    for name in SERVICES:
        hass.services.async_remove(DOMAIN, name)
