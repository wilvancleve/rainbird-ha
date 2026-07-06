"""Switch platform: one switch per irrigation zone."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainbirdCoordinator
from .entity import RainbirdEntity
from .client.iq4 import Station

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: RainbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [RainbirdControllerPower(coordinator)]
    entities += [
        RainbirdZoneSwitch(coordinator, station)
        for station in coordinator.data.stations
    ]
    async_add_entities(entities)


class RainbirdControllerPower(RainbirdEntity, SwitchEntity):
    """Master controller On (Auto) / Off.

    Writes the dial position (logicalDialPos 2=On, 1=Off); real state is read
    back from the controller's ``isShutdown`` flag.
    """

    _attr_name = "Controller"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_power"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_power(self.coordinator.satellite_id, True)
        self.coordinator.data.power_on = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_power(self.coordinator.satellite_id, False)
        self.coordinator.data.power_on = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class RainbirdZoneSwitch(RainbirdEntity, SwitchEntity):
    """A single irrigation zone; on = running, off = stopped."""

    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator: RainbirdCoordinator, station: Station) -> None:
        super().__init__(coordinator)
        self._station_id = station.id
        self._attr_unique_id = f"{coordinator.satellite_id}_zone_{station.id}"
        self._attr_name = station.name

    @property
    def _minutes(self) -> int:
        return self.coordinator.zone_run_minutes(self._station_id)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.active_station_id == self._station_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"station_id": self._station_id}
        if self.is_on and self.coordinator.data.remain_seconds is not None:
            attrs["remaining_seconds"] = self.coordinator.data.remain_seconds
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        minutes = kwargs.get("duration_minutes", self._minutes)
        _LOGGER.info("Starting zone %s for %s min", self._station_id, minutes)
        await self.coordinator.client.start_station(self._station_id, minutes)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info("Stopping zone %s", self._station_id)
        await self.coordinator.client.stop_stations([self._station_id])
        await self.coordinator.async_request_refresh()
