"""Switches for My Koleos LATAM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import get_path
from .coordinator import MyKoleosCoordinator
from .entity import MyKoleosEntity, vehicle_status


@dataclass(frozen=True, kw_only=True)
class MyKoleosSwitchDescription(SwitchEntityDescription):
    """Switch description."""

    on_command: str
    off_command: str


SWITCHES: tuple[MyKoleosSwitchDescription, ...] = (
    MyKoleosSwitchDescription(
        key="remote_climate",
        name="Climatização remota",
        icon="mdi:snowflake",
        on_command="hvac_start",
        off_command="hvac_stop",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Koleos switches."""
    coordinator: MyKoleosCoordinator = entry.runtime_data
    async_add_entities(MyKoleosSwitch(coordinator, description) for description in SWITCHES)


class MyKoleosSwitch(MyKoleosEntity, SwitchEntity):
    """My Koleos switch."""

    entity_description: MyKoleosSwitchDescription

    def __init__(self, coordinator: MyKoleosCoordinator, description: MyKoleosSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        status = vehicle_status(self.coordinator.data or {})
        value: Any = get_path(status, "additionalVehicleStatus.climateStatus.preClimateActive")
        if value is None:
            return None
        return str(value).lower() == "true"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start remote climate."""
        await self.coordinator.async_send_remote_command(self.entity_description.on_command)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop remote climate."""
        await self.coordinator.async_send_remote_command(self.entity_description.off_command)
        await self.coordinator.async_request_refresh()
