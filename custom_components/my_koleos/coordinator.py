"""Data coordinator for My Koleos LATAM."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MyKoleosApi, MyKoleosAuthError, MyKoleosConnectionError, MyKoleosError, REMOTE_PROXY_COMMANDS, get_path, to_float, to_int
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_EXPIRES_AT,
    CONF_ENABLE_REMOTE_COMMANDS,
    CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS,
    CONF_REMOTE_COMMAND_COOLDOWN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DEFAULT_ENABLE_REMOTE_COMMANDS,
    DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS,
    DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class MyKoleosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that refreshes tokens and polls vehicle data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: MyKoleosApi,
        *,
        idle_interval: timedelta,
        active_interval: timedelta,
        adaptive_polling: bool,
        update_session_on_poll: bool,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=active_interval if adaptive_polling else idle_interval,
        )
        self.entry = entry
        self.api = api
        self.idle_interval = idle_interval
        self.active_interval = active_interval
        self.adaptive_polling = adaptive_polling
        self.update_session_on_poll = update_session_on_poll
        self.vehicle_active = False
        self._refresh_lock = asyncio.Lock()
        self._fetch_lock = asyncio.Lock()
        self._remote_command_lock = asyncio.Lock()
        self._last_remote_command_monotonic = 0.0

    def _token_expires_soon(self, margin_seconds: int = 300) -> bool:
        """Return true when the current access token should be renewed."""
        expires_at = self.api.tokens.expires_at if self.api.tokens else None
        if not expires_at:
            # Older entries did not always persist expires_at. Avoid refreshing on every
            # poll; let a 401 trigger a single guarded refresh instead.
            return False
        return datetime.now(UTC).timestamp() >= expires_at - margin_seconds

    async def _async_refresh_tokens_if_needed(self) -> None:
        if self._token_expires_soon():
            await self.async_refresh_tokens(force=False)

    async def async_refresh_tokens(self, *, force: bool = True) -> None:
        """Refresh ECARX tokens and persist the new pair in the config entry.

        ECARX rotates accessToken and refreshToken together. A concurrent double
        refresh can invalidate the pair another task is about to use, which causes
        HTTP 401 / 1404 and unnecessary reauth. Keep refresh serialized.
        """
        async with self._refresh_lock:
            if not force and not self._token_expires_soon():
                return
            tokens = await self.api.refresh()
            new_data = dict(self.entry.data)
            new_data.update(
                {
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_USER_ID: tokens.user_id,
                    CONF_CLIENT_ID: tokens.client_id,
                    CONF_EXPIRES_AT: tokens.expires_at,
                }
            )
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    @staticmethod
    def _vehicle_is_active(data: dict[str, Any]) -> bool:
        """Infer whether the cloud data suggests the car is awake/in use."""
        status = data.get("status") or data.get("session") or {}
        vehicle_status = status.get("vehicleStatus") if isinstance(status, dict) else {}
        vehicle_status = vehicle_status if isinstance(vehicle_status, dict) else {}
        state = data.get("state") or {}
        state = state if isinstance(state, dict) else {}

        engine_status = str(get_path(vehicle_status, "basicVehicleStatus.engineStatus", "")).lower()
        speed = to_float(get_path(vehicle_status, "basicVehicleStatus.speed")) or 0
        engine_state = to_int(get_path(state, "engineState"))
        pre_climate = str(get_path(vehicle_status, "additionalVehicleStatus.climateStatus.preClimateActive", "false")).lower()
        air_blower = str(get_path(vehicle_status, "additionalVehicleStatus.climateStatus.airBlowerActive", "false")).lower()
        rmac_active = str(get_path(state, "rmacActive", "0")).lower()

        return any(
            (
                engine_status == "engine_on",
                speed > 1,
                engine_state not in (None, 0),
                pre_climate == "true",
                air_blower == "true",
                rmac_active not in ("0", "false", "none", ""),
            )
        )

    def _apply_adaptive_interval(self, data: dict[str, Any]) -> None:
        if not self.adaptive_polling:
            self.vehicle_active = False
            self.update_interval = self.idle_interval
            return
        self.vehicle_active = self._vehicle_is_active(data)
        self.update_interval = self.active_interval if self.vehicle_active else self.idle_interval

    def _with_diagnostics(self, data: dict[str, Any], *, forced: bool = False) -> dict[str, Any]:
        """Apply adaptive interval and append coordinator diagnostics."""
        self._apply_adaptive_interval(data)
        data["diagnostics"] = {
            "vehicle_active": self.vehicle_active,
            "poll_interval_seconds": int((self.update_interval or self.idle_interval).total_seconds()),
            "adaptive_polling": self.adaptive_polling,
            "update_session_on_poll": self.update_session_on_poll,
            "last_update_forced": forced,
        }
        return data

    async def _fetch_vehicle_data_once(self, *, force_update_session: bool = False) -> dict[str, Any]:
        """Fetch session/status/state once with the currently loaded token pair."""
        session: dict[str, Any] = {}

        should_update_session = self.update_session_on_poll or force_update_session
        if should_update_session:
            session = await self.api.update_session()
            status = (
                session
                if get_path(session, "vehicleStatus")
                else await self.api.status(latest="false" if force_update_session else "local")
            )
        else:
            status = await self.api.status()

        state = await self.api.state()
        return {"session": session, "status": status, "state": state}

    async def _fetch_vehicle_data(self, *, force_update_session: bool = False) -> dict[str, Any]:
        """Fetch session/status/state from the cloud.

        Serialize the full poll cycle and retry once after a guarded refresh when
        any authenticated request rejects the token. Only the second failure asks
        Home Assistant for reauth.
        """
        async with self._fetch_lock:
            await self._async_refresh_tokens_if_needed()
            try:
                return await self._fetch_vehicle_data_once(force_update_session=force_update_session)
            except MyKoleosAuthError:
                _LOGGER.debug("Token rejected during vehicle poll; refreshing once and retrying")
                await self.async_refresh_tokens(force=True)
                return await self._fetch_vehicle_data_once(force_update_session=force_update_session)

    async def async_force_vehicle_update(self) -> None:
        """Force an immediate cloud update and push data to entities."""
        try:
            data = await self._fetch_vehicle_data(force_update_session=True)
            self.async_set_updated_data(self._with_diagnostics(data, forced=True))
        except MyKoleosAuthError as exc:
            raise ConfigEntryAuthFailed(f"Authentication failed: {exc}") from exc
        except MyKoleosConnectionError as exc:
            raise UpdateFailed(f"Connection failed: {exc}") from exc


    def _entry_option_bool(self, key: str, default: bool) -> bool:
        return bool(self.entry.options.get(key, self.entry.data.get(key, default)))

    def _entry_option_int(self, key: str, default: int) -> int:
        return int(self.entry.options.get(key, self.entry.data.get(key, default)))

    def _remote_definition_for(self, command: str, path: str | None) -> dict[str, Any]:
        if command in REMOTE_PROXY_COMMANDS:
            return REMOTE_PROXY_COMMANDS[command]
        if path:
            for definition in REMOTE_PROXY_COMMANDS.values():
                if definition.get("path") == path:
                    return definition
        return {}

    async def async_send_remote_command(
        self,
        command: str,
        *,
        payload: dict[str, Any] | None = None,
        method: str | None = None,
        backend: str = "auto",
        path: str | None = None,
        merge_defaults: bool = True,
    ) -> dict[str, Any]:
        """Send an experimental remote command serialized with polling/refresh."""
        if not self._entry_option_bool(CONF_ENABLE_REMOTE_COMMANDS, DEFAULT_ENABLE_REMOTE_COMMANDS):
            raise MyKoleosError("Comandos remotos estão desativados. Ative nas opções da integração.")
        definition = self._remote_definition_for(command, path)
        if definition.get("sensitive") and not self._entry_option_bool(
            CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS, DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS
        ):
            raise MyKoleosError("Comando remoto sensível bloqueado. Ative 'Permitir comandos sensíveis' nas opções.")

        cooldown = self._entry_option_int(CONF_REMOTE_COMMAND_COOLDOWN, DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS)
        now = time.monotonic()
        if cooldown > 0 and now - self._last_remote_command_monotonic < cooldown:
            wait = int(cooldown - (now - self._last_remote_command_monotonic)) + 1
            raise MyKoleosError(f"Cooldown de comando remoto ativo; aguarde {wait}s.")

        async with self._remote_command_lock:
            async with self._fetch_lock:
                await self._async_refresh_tokens_if_needed()
                result = await self.api.send_proxy_command(
                    command,
                    payload=payload,
                    method=method,
                    path=path,
                    backend=backend,
                    merge_defaults=merge_defaults,
                )
                self._last_remote_command_monotonic = time.monotonic()
                current = dict(self.data or {})
                current["last_remote_command"] = {
                    "command": command,
                    "backend": backend,
                    "path": path or definition.get("path"),
                    "result": result,
                }
                self.async_set_updated_data(current)
                return result

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self._fetch_vehicle_data(force_update_session=False)
            return self._with_diagnostics(data)
        except MyKoleosAuthError as exc:
            raise ConfigEntryAuthFailed(f"Authentication failed: {exc}") from exc
        except MyKoleosConnectionError as exc:
            raise UpdateFailed(f"Connection failed: {exc}") from exc

