"""Entity helpers for My Koleos LATAM."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_INSTANCE_ID, DOMAIN
from .coordinator import MyKoleosCoordinator


class MyKoleosEntity(CoordinatorEntity[MyKoleosCoordinator]):
    """Base class for My Koleos entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MyKoleosCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        vin = coordinator.api.vin or "unknown"
        instance_id = coordinator.entry.data.get(CONF_INSTANCE_ID)
        self._attr_unique_id = f"{instance_id}_{vin}_{key}" if instance_id else f"{vin}_{key}"
        # Keep automatically generated entity_ids compact and stable for new installs:
        # sensor.koleos_odometer, switch.koleos_remote_climate, etc.
        self._attr_suggested_object_id = f"koleos_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        vin = self.coordinator.api.vin or "unknown"
        model = self.coordinator.api.model_code or "Koleos"
        instance_id = self.coordinator.entry.data.get(CONF_INSTANCE_ID)
        identifier = instance_id or vin
        name = "Koleos"
        if instance_id:
            name = "Koleos hub"
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="Renault",
            name=name,
            model=model,
            serial_number=vin,
            configuration_url="https://my-rk-latam.renaultkoream.com/",
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)


def status_root(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return the status payload root."""
    if not data:
        return {}
    status = data.get("status") or {}
    if isinstance(status, dict) and "vehicleStatus" in status:
        return status
    session = data.get("session") or {}
    if isinstance(session, dict) and "vehicleStatus" in session:
        return session
    return status if isinstance(status, dict) else {}


def vehicle_status(data: dict[str, Any] | None) -> dict[str, Any]:
    root = status_root(data)
    vs = root.get("vehicleStatus") if isinstance(root, dict) else None
    return vs if isinstance(vs, dict) else {}


def state_root(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    state = data.get("state")
    return state if isinstance(state, dict) else {}
