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
    async_add_entities([RainbirdConnectivity(coordinator)])


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
