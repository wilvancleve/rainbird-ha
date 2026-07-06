"""Number platform: rain delay (days) and per-zone run time (minutes)."""

from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEFAULT_MINUTES, DEFAULT_MINUTES, DOMAIN
from .coordinator import RainbirdCoordinator
from .entity import RainbirdEntity

_LOGGER = logging.getLogger(__name__)

MAX_RAIN_DELAY_DAYS = 14
MAX_RUN_MINUTES = 240


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: RainbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = [RainbirdRainDelay(coordinator)]
    entities += [
        RainbirdZoneRunTime(coordinator, station)
        for station in coordinator.data.stations
    ]
    async_add_entities(entities)


class RainbirdRainDelay(RainbirdEntity, NumberEntity):
    """Rain delay in days; 0 clears it."""

    _attr_name = "Rain delay"
    _attr_icon = "mdi:weather-rainy"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_RAIN_DELAY_DAYS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_rain_delay"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.rain_delay

    async def async_set_native_value(self, value: float) -> None:
        days = int(value)
        _LOGGER.info("Setting rain delay to %s day(s)", days)
        await self.coordinator.client.set_rain_delay(self.coordinator.satellite_id, days)
        self.coordinator.data.rain_delay = days
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class RainbirdZoneRunTime(RainbirdEntity, RestoreNumber):
    """Per-zone run duration (minutes) applied when that zone's switch turns on.

    A local setting -- no cloud call. Restored across restarts, and always
    editable regardless of controller connectivity. This is the guardrail that
    keeps a zone from being started without a defined, device-enforced runtime.
    """

    _attr_icon = "mdi:timer-cog-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = MAX_RUN_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RainbirdCoordinator, station) -> None:
        super().__init__(coordinator)
        self._station_id = station.id
        self._attr_unique_id = f"{coordinator.satellite_id}_zone_{station.id}_runtime"
        self._attr_name = f"{station.name} run time"
        default = coordinator.config_entry.options.get(
            CONF_DEFAULT_MINUTES, DEFAULT_MINUTES
        )
        self._attr_native_value = default
        coordinator.zone_minutes.setdefault(station.id, default)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = int(last.native_value)
        self.coordinator.zone_minutes[self._station_id] = int(self._attr_native_value)

    # Always editable -- it's just a setting, independent of controller state.
    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int:
        return int(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = int(value)
        self.coordinator.zone_minutes[self._station_id] = int(value)
        self.async_write_ha_state()
