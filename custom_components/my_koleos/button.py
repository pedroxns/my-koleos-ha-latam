"""Buttons for My Koleos LATAM."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MyKoleosCoordinator
from .entity import MyKoleosEntity


@dataclass(frozen=True, kw_only=True)
class MyKoleosButtonDescription(ButtonEntityDescription):
    """Button description."""

    press_action: str


BUTTONS: tuple[MyKoleosButtonDescription, ...] = (
    MyKoleosButtonDescription(
        key="refresh_now",
        translation_key="refresh_now",
        name="Atualizar agora",
        icon="mdi:car-connected",
        press_action="refresh_now",
    ),
    MyKoleosButtonDescription(
        key="refresh_tokens",
        translation_key="refresh_tokens",
        name="Renovar sessão",
        icon="mdi:key-sync-outline",
        entity_category=EntityCategory.CONFIG,
        press_action="refresh_tokens",
    ),
    MyKoleosButtonDescription(
        key="find_my_car",
        translation_key="find_my_car",
        name="Localizar carro",
        icon="mdi:map-marker-radius",
        entity_category=EntityCategory.CONFIG,
        press_action="remote:find_my_car",
    ),
    MyKoleosButtonDescription(
        key="horn_lights",
        translation_key="horn_lights",
        name="Buzina e luzes",
        icon="mdi:bullhorn-outline",
        entity_category=EntityCategory.CONFIG,
        press_action="remote:horn_lights",
    ),
    MyKoleosButtonDescription(
        key="hvac_start",
        translation_key="hvac_start",
        name="Ligar climatização",
        icon="mdi:snowflake",
        entity_category=EntityCategory.CONFIG,
        press_action="remote:hvac_start",
    ),
    MyKoleosButtonDescription(
        key="hvac_stop",
        translation_key="hvac_stop",
        name="Desligar climatização",
        icon="mdi:snowflake-off",
        entity_category=EntityCategory.CONFIG,
        press_action="remote:hvac_stop",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Koleos buttons."""
    coordinator: MyKoleosCoordinator = entry.runtime_data
    async_add_entities(MyKoleosButton(coordinator, description) for description in BUTTONS)


class MyKoleosButton(MyKoleosEntity, ButtonEntity):
    """My Koleos button."""

    entity_description: MyKoleosButtonDescription

    def __init__(self, coordinator: MyKoleosCoordinator, description: MyKoleosButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Run the button action."""
        if self.entity_description.press_action == "refresh_tokens":
            await self.coordinator.async_refresh_tokens(force=True)
            await self.coordinator.async_request_refresh()
            return
        if self.entity_description.press_action.startswith("remote:"):
            command = self.entity_description.press_action.split(":", 1)[1]
            await self.coordinator.async_send_remote_command(command)
            return
        await self.coordinator.async_force_vehicle_update()
