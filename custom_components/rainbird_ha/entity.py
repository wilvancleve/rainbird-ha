"""Base entity for rainbird_ha."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainbirdCoordinator


class RainbirdEntity(CoordinatorEntity[RainbirdCoordinator]):
    """Base entity tied to one controller (satellite)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RainbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.satellite_id))},
            manufacturer="Rain Bird",
            name=coordinator.config_entry.data.get("satellite_name", "Rain Bird"),
            model="IQ4 controller",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.connected
