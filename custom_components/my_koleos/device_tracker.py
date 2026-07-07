"""Device tracker for My Koleos LATAM."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import decode_position, get_path
from .coordinator import MyKoleosCoordinator
from .entity import MyKoleosEntity, vehicle_status


class MyKoleosDeviceTracker(MyKoleosEntity, TrackerEntity):
    """GPS tracker for the vehicle."""

    _attr_translation_key = "location"
    _attr_name = "Localização"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: MyKoleosCoordinator) -> None:
        super().__init__(coordinator, "location")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return decode_position(get_path(vehicle_status(self.coordinator.data), "basicVehicleStatus.position.latitude"))

    @property
    def longitude(self) -> float | None:
        return decode_position(get_path(vehicle_status(self.coordinator.data), "basicVehicleStatus.position.longitude"))

    @property
    def location_accuracy(self) -> int:
        return 100

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        pos = get_path(vehicle_status(self.coordinator.data), "basicVehicleStatus.position", {}) or {}
        return {
            "trusted": pos.get("posCanBeTrusted"),
            "mars_coordinates": pos.get("marsCoordinates"),
            "upload_enabled": pos.get("carLocatorStatUploadEn"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Koleos tracker."""
    coordinator: MyKoleosCoordinator = entry.runtime_data
    async_add_entities([MyKoleosDeviceTracker(coordinator)])
