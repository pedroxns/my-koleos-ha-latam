"""Sensors for My Koleos LATAM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfElectricPotential, UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import epoch_ms, get_path, to_float, to_int
from .coordinator import MyKoleosCoordinator
from .entity import MyKoleosEntity, state_root, vehicle_status

ValueFn = Callable[[dict[str, Any]], Any]


def vs_path(path: str, cast: Callable[[Any], Any] = lambda value: value) -> ValueFn:
    def _value(data: dict[str, Any]) -> Any:
        return cast(get_path(vehicle_status(data), path))

    return _value


def state_path(path: str, cast: Callable[[Any], Any] = lambda value: value) -> ValueFn:
    def _value(data: dict[str, Any]) -> Any:
        return cast(get_path(state_root(data), path))

    return _value


def diag_path(path: str, cast: Callable[[Any], Any] = lambda value: value) -> ValueFn:
    def _value(data: dict[str, Any]) -> Any:
        diagnostics = data.get("diagnostics") if isinstance(data, dict) else {}
        return cast(get_path(diagnostics or {}, path))

    return _value


def kpa_to_psi(value: Any) -> float | None:
    """Convert pressure from kPa to psi."""
    number = to_float(value)
    if number is None:
        return None
    return round(number / 6.8947572932, 1)


def alarm_state(data: dict[str, Any]) -> str | None:
    """Return a user-friendly alarm state."""
    value = get_path(vehicle_status(data), "additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm.alrmTrgSrc")
    if value is None:
        return None
    return "inativo" if str(value).lower() in ("0", "false", "none", "") else "ativado"


@dataclass(frozen=True, kw_only=True)
class MyKoleosSensorDescription(SensorEntityDescription):
    """Sensor description."""

    value_fn: ValueFn


SENSORS: tuple[MyKoleosSensorDescription, ...] = (
    MyKoleosSensorDescription(
        key="odometer",
        translation_key="odometer",
        name="Odômetro",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.odometer", to_float),
    ),
    MyKoleosSensorDescription(
        key="distance_to_empty",
        translation_key="distance_to_empty",
        name="Autonomia",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("basicVehicleStatus.distanceToEmpty", to_float),
    ),
    MyKoleosSensorDescription(
        key="fuel_level_pct",
        translation_key="fuel_level_pct",
        name="Combustível percentual",
        icon="mdi:gas-station",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.runningStatus.fuelLevelPct", to_float),
    ),
    MyKoleosSensorDescription(
        key="fuel_level_liters",
        translation_key="fuel_level_liters",
        name="Volume de combustível",
        icon="mdi:gas-station-outline",
        native_unit_of_measurement="L",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.runningStatus.fuelLevel", to_float),
    ),
    MyKoleosSensorDescription(
        key="average_fuel_consumption",
        translation_key="average_fuel_consumption",
        name="Consumo médio",
        icon="mdi:fuel",
        native_unit_of_measurement="km/L",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.runningStatus.aveFuelConsumption", to_float),
    ),
    MyKoleosSensorDescription(
        key="avg_speed",
        translation_key="avg_speed",
        name="Velocidade média",
        icon="mdi:speedometer-medium",
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.runningStatus.avgSpeed", to_float),
    ),
    MyKoleosSensorDescription(
        key="external_temperature",
        translation_key="external_temperature",
        name="Temperatura externa",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.climateStatus.exteriorTemp", to_float),
    ),
    MyKoleosSensorDescription(
        key="interior_temperature",
        translation_key="interior_temperature",
        name="Temperatura interna",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.climateStatus.interiorTemp", to_float),
    ),
    MyKoleosSensorDescription(
        key="coolant_temperature",
        translation_key="coolant_temperature",
        name="Temperatura do motor",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.runningStatus.engineCoolantTemperature", to_float),
    ),
    MyKoleosSensorDescription(
        key="battery_12v_voltage",
        translation_key="battery_12v_voltage",
        name="Bateria 12V",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.voltage", to_float),
    ),
    MyKoleosSensorDescription(
        key="battery_12v_charge",
        translation_key="battery_12v_charge",
        name="Carga bateria 12V",
        icon="mdi:battery-heart",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.chargeLevel", to_float),
    ),
    MyKoleosSensorDescription(
        key="hybrid_battery_charge",
        translation_key="hybrid_battery_charge",
        name="Carga bateria híbrida/EV",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.electricVehicleStatus.chargeLevel", to_float),
    ),
    MyKoleosSensorDescription(
        key="distance_to_service",
        translation_key="distance_to_service",
        name="Distância até revisão",
        icon="mdi:wrench-clock",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.distanceToService", to_float),
    ),
    MyKoleosSensorDescription(
        key="days_to_service",
        translation_key="days_to_service",
        name="Dias até revisão",
        icon="mdi:calendar-clock",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.daysToService", to_int),
    ),
    MyKoleosSensorDescription(
        key="tire_pressure_fl",
        translation_key="tire_pressure_fl",
        name="Pressão pneu dianteiro esquerdo",
        icon="mdi:car-tire-alert",
        native_unit_of_measurement="psi",
        # Intentionally no pressure device_class: HA converts pressure device_class
        # to the user's preferred unit system, which often displays kPa.
        # Keeping this as a plain measurement forces tire pressure to remain psi.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.tyreStatusDriver", kpa_to_psi),
    ),
    MyKoleosSensorDescription(
        key="tire_pressure_fr",
        translation_key="tire_pressure_fr",
        name="Pressão pneu dianteiro direito",
        icon="mdi:car-tire-alert",
        native_unit_of_measurement="psi",
        # Intentionally no pressure device_class: HA converts pressure device_class
        # to the user's preferred unit system, which often displays kPa.
        # Keeping this as a plain measurement forces tire pressure to remain psi.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.tyreStatusPassenger", kpa_to_psi),
    ),
    MyKoleosSensorDescription(
        key="tire_pressure_rl",
        translation_key="tire_pressure_rl",
        name="Pressão pneu traseiro esquerdo",
        icon="mdi:car-tire-alert",
        native_unit_of_measurement="psi",
        # Intentionally no pressure device_class: HA converts pressure device_class
        # to the user's preferred unit system, which often displays kPa.
        # Keeping this as a plain measurement forces tire pressure to remain psi.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.tyreStatusDriverRear", kpa_to_psi),
    ),
    MyKoleosSensorDescription(
        key="tire_pressure_rr",
        translation_key="tire_pressure_rr",
        name="Pressão pneu traseiro direito",
        icon="mdi:car-tire-alert",
        native_unit_of_measurement="psi",
        # Intentionally no pressure device_class: HA converts pressure device_class
        # to the user's preferred unit system, which often displays kPa.
        # Keeping this as a plain measurement forces tire pressure to remain psi.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=vs_path("additionalVehicleStatus.maintenanceStatus.tyreStatusPassengerRear", kpa_to_psi),
    ),

    MyKoleosSensorDescription(
        key="vehicle_alarm_status",
        translation_key="vehicle_alarm_status",
        name="Alarme disparado",
        icon="mdi:shield-car",
        value_fn=alarm_state,
    ),
    MyKoleosSensorDescription(
        key="last_update",
        translation_key="last_update",
        name="Última atualização",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=vs_path("updateTime", epoch_ms),
    ),
    MyKoleosSensorDescription(
        key="next_wakeup",
        translation_key="next_wakeup",
        name="Próximo wake-up",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("nextWakeupTime", epoch_ms),
    ),
    MyKoleosSensorDescription(
        key="poll_interval",
        translation_key="poll_interval",
        name="Intervalo de atualização",
        icon="mdi:timer-sync-outline",
        native_unit_of_measurement="s",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=diag_path("poll_interval_seconds", to_int),
    ),
    MyKoleosSensorDescription(
        key="power_mode",
        translation_key="power_mode",
        name="Modo de energia",
        icon="mdi:power-plug-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("powerMode"),
    ),
    MyKoleosSensorDescription(
        key="engine_state",
        translation_key="engine_state",
        name="Estado do motor",
        icon="mdi:engine-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("engineState", to_int),
    ),
    MyKoleosSensorDescription(
        key="svt_state",
        translation_key="svt_state",
        name="SVT",
        icon="mdi:shield-car",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("svtState", to_int),
    ),
    MyKoleosSensorDescription(
        key="park_comfort_state",
        translation_key="park_comfort_state",
        name="Park comfort",
        icon="mdi:car-seat-cooler",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("parkComfortState", to_int),
    ),
    MyKoleosSensorDescription(
        key="drift_mode_active",
        translation_key="drift_mode_active",
        name="Drift mode",
        icon="mdi:car-sports",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=state_path("driftModeActive", to_int),
    ),
)


class MyKoleosSensor(MyKoleosEntity, SensorEntity):
    """My Koleos sensor."""

    entity_description: MyKoleosSensorDescription

    def __init__(self, coordinator: MyKoleosCoordinator, description: MyKoleosSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Koleos sensors."""
    coordinator: MyKoleosCoordinator = entry.runtime_data
    async_add_entities(MyKoleosSensor(coordinator, description) for description in SENSORS)
