"""Binary sensors for My Koleos LATAM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import get_path, to_int
from .coordinator import MyKoleosCoordinator
from .entity import MyKoleosEntity, state_root, vehicle_status

BoolFn = Callable[[dict[str, Any]], bool | None]


def value_is(path: str, expected: Any) -> BoolFn:
    def _value(data: dict[str, Any]) -> bool | None:
        value = get_path(vehicle_status(data), path)
        if value is None:
            return None
        return str(value).lower() == str(expected).lower()

    return _value


def value_not(path: str, unexpected: Any) -> BoolFn:
    def _value(data: dict[str, Any]) -> bool | None:
        value = get_path(vehicle_status(data), path)
        if value is None:
            return None
        return str(value).lower() != str(unexpected).lower()

    return _value


def state_is(path: str, expected: Any) -> BoolFn:
    def _value(data: dict[str, Any]) -> bool | None:
        value = get_path(state_root(data), path)
        if value is None:
            return None
        return str(value).lower() == str(expected).lower()

    return _value


@dataclass(frozen=True, kw_only=True)
class MyKoleosBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description."""

    value_fn: BoolFn


BINARY_SENSORS: tuple[MyKoleosBinarySensorDescription, ...] = (
    MyKoleosBinarySensorDescription(
        key="engine_on",
        translation_key="engine_on",
        name="Motor",
        value_fn=lambda data: (get_path(vehicle_status(data), "basicVehicleStatus.engineStatus") == "engine_on")
        or (to_int(get_path(state_root(data), "engineState")) not in (None, 0)),
    ),
    MyKoleosBinarySensorDescription(
        key="central_locked",
        translation_key="central_locked",
        name="Travamento central",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=value_is("additionalVehicleStatus.drivingSafetyStatus.centralLockingStatus", "1"),
    ),
    MyKoleosBinarySensorDescription(
        key="driver_door_open",
        translation_key="driver_door_open",
        name="Porta motorista",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusDriver", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="passenger_door_open",
        translation_key="passenger_door_open",
        name="Porta passageiro",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusPassenger", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="rear_left_door_open",
        translation_key="rear_left_door_open",
        name="Porta traseira esquerda",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusDriverRear", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="rear_right_door_open",
        translation_key="rear_right_door_open",
        name="Porta traseira direita",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusPassengerRear", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="trunk_open",
        translation_key="trunk_open",
        name="Porta-malas",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.trunkOpenStatus", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="hood_open",
        translation_key="hood_open",
        name="Capô",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=value_not("additionalVehicleStatus.drivingSafetyStatus.engineHoodOpenStatus", "0"),
    ),
    MyKoleosBinarySensorDescription(
        key="activated",
        translation_key="activated",
        name="Serviço conectado ativo",
        value_fn=state_is("activateState", "1"),
    ),
)


class MyKoleosBinarySensor(MyKoleosEntity, BinarySensorEntity):
    """My Koleos binary sensor."""

    entity_description: MyKoleosBinarySensorDescription

    def __init__(self, coordinator: MyKoleosCoordinator, description: MyKoleosBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data or {})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Koleos binary sensors."""
    coordinator: MyKoleosCoordinator = entry.runtime_data
    async_add_entities(MyKoleosBinarySensor(coordinator, description) for description in BINARY_SENSORS)

