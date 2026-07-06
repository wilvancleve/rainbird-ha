"""Sensor platform: active zone and remaining run time."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainbirdCoordinator
from .entity import RainbirdEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: RainbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        RainbirdActiveZone(coordinator),
        RainbirdRemaining(coordinator),
    ]
    entities += [
        RainbirdProgram(coordinator, p["id"]) for p in coordinator.data.programs
    ]
    async_add_entities(entities)


class RainbirdProgram(RainbirdEntity, SensorEntity):
    """One program's schedule: state is its days summary, detail in attributes."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: RainbirdCoordinator, program_id: int) -> None:
        super().__init__(coordinator)
        self._program_id = program_id
        self._attr_unique_id = f"{coordinator.satellite_id}_program_{program_id}"
        p = coordinator.program(program_id) or {}
        self._attr_name = f"Program {p.get('short') or p.get('name') or program_id}"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        p = self.coordinator.program(self._program_id)
        if not p:
            return "Unknown"
        times = ", ".join(t["time"] for t in p["start_times"])
        if p["runs"] and times:
            return f"{p['days']} @ {times}"
        return "Off" if not p["runs"] else p["days"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.coordinator.program(self._program_id)
        if not p:
            return {}
        return {
            "program_id": p["id"],
            "name": p["name"],
            "days": p["days"],
            "days_mask": p["days_mask"],
            "start_times": [t["time"] for t in p["start_times"]],
            "seasonal_adjust_pct": p["seasonal_adjust"],
            "stations": [
                {"terminal": s["terminal"], "minutes": s["minutes"]}
                for s in p["stations"]
            ],
        }


class RainbirdActiveZone(RainbirdEntity, SensorEntity):
    """Name of the currently-running zone, or 'Idle'."""

    _attr_name = "Active zone"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_active_zone"

    @property
    def native_value(self) -> str:
        active = self.coordinator.data.active_station_id
        if active is None:
            return "Idle"
        for s in self.coordinator.data.stations:
            if s.id == active:
                return s.name
        return f"Station {active}"


class RainbirdRemaining(RainbirdEntity, SensorEntity):
    """Seconds remaining on the active zone."""

    _attr_name = "Time remaining"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_remaining"

    @property
    def native_value(self) -> int:
        if self.coordinator.data.active_station_id is None:
            return 0
        return self.coordinator.data.remain_seconds or 0
