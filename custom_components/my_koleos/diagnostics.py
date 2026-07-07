"""Diagnostics support for My Koleos LATAM."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_APP_SECRET,
    CONF_CLIENT_ID,
    CONF_LATAM_AUTH_TOKEN,
    CONF_LATAM_USER_ID,
    CONF_DEVICE_IDENTIFIER,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
)

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_APP_SECRET,
    CONF_CLIENT_ID,
    CONF_LATAM_AUTH_TOKEN,
    CONF_LATAM_USER_ID,
    CONF_DEVICE_IDENTIFIER,
    CONF_USER_ID,
    "Authorization",
    "authToken",
    "latam_auth_token",
    "latam_user_id",
    "accessToken",
    "refreshToken",
    "app_secret",
    "clientId",
    "userId",
    "imei",
    "imsi",
    "iccId",
    "msisdn",
    "latitude",
    "longitude",
    "position",
}


def _summarize_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    status = data.get("status") or data.get("session") or {}
    vehicle_status = status.get("vehicleStatus") if isinstance(status, dict) else {}
    vehicle_status = vehicle_status if isinstance(vehicle_status, dict) else {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
    return {
        "has_status": bool(vehicle_status),
        "has_state": bool(state),
        "update_time": vehicle_status.get("updateTime"),
        "diagnostics": diagnostics,
        "state_keys": sorted(state.keys()) if state else [],
        "vehicle_status_sections": sorted(vehicle_status.keys()) if vehicle_status else [],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry without secrets or coordinates."""
    coordinator = getattr(entry, "runtime_data", None)
    data = getattr(coordinator, "data", None)
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options, TO_REDACT),
        "runtime": async_redact_data(_summarize_data(data), TO_REDACT),
    }
