"""Binary sensor platform: controller connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainbirdCoordinator
from .entity import RainbirdEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: RainbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [RainbirdConnectivity(coordinator)]
    # Only add the moisture/rain sensor if the controller actually has one wired.
    if coordinator.data.sensor_active is not None:
        entities.append(RainbirdMoistureSensor(coordinator))
    async_add_entities(entities)


class RainbirdMoistureSensor(RainbirdEntity, BinarySensorEntity):
    """The controller's on-board rain/soil-moisture sensor (on = sensing/wet).

    Backed by the local sensor's ``onOffState``. The on/wet polarity should be
    confirmed against the physical sensor; invert here if it reads backwards.
    """

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_name = "Moisture sensor"
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_moisture"

    @property
    def available(self) -> bool:
        return (self.coordinator.last_update_success
                and self.coordinator.data.sensor_active is not None)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.sensor_active)


class RainbirdConnectivity(RainbirdEntity, BinarySensorEntity):
    """Whether the controller is reachable via the cloud."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Connectivity"

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.satellite_id}_connectivity"

    # This sensor must report even when the controller is offline.
    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.connected
