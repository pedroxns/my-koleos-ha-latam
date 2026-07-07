"""Config flow for My Koleos LATAM."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MyKoleosApi, MyKoleosAuthError, MyKoleosConnectionError, gigya_login_url
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACTIVE_SCAN_INTERVAL,
    CONF_ADAPTIVE_POLLING,
    CONF_APP_SECRET,
    CONF_AUTH_CODE,
    CONF_CLIENT_ID,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_IDENTIFIER,
    CONF_ENABLE_REMOTE_COMMANDS,
    CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS,
    CONF_LATAM_AUTH_TOKEN,
    CONF_LATAM_USER_ID,
    CONF_REMOTE_COMMAND_COOLDOWN,
    CONF_EXPIRES_AT,
    CONF_IDLE_SCAN_INTERVAL,
    CONF_INSTANCE_ID,
    CONF_MODEL_CODE,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_SESSION_ON_POLL,
    CONF_USER_ID,
    CONF_VIN,
    DEFAULT_ACTIVE_SCAN_INTERVAL,
    DEFAULT_ADAPTIVE_POLLING,
    DEFAULT_APP_SECRET,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_DEVICE_IDENTIFIER,
    DEFAULT_ENABLE_REMOTE_COMMANDS,
    DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS,
    DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS,
    DEFAULT_IDLE_SCAN_INTERVAL,
    DEFAULT_MODEL_CODE,
    DEFAULT_UPDATE_SESSION_ON_POLL,
    MIN_SCAN_INTERVAL_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_LOGIN_URL = "login_url"
CONF_REDIRECT_URL_OR_CODE = "redirect_url_or_code"


def _extract_auth_code(value: str) -> str:
    """Return OAuth code from either a raw code or a full redirect URL."""
    value = (value or "").strip()
    if not value:
        return ""

    parsed = urlparse(value.replace("#", "?"))
    query = parse_qs(parsed.query)
    code_values = query.get("code")
    if code_values and code_values[0]:
        return code_values[0].strip()
    return value


class MyKoleosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Koleos LATAM."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Create the options flow."""
        return MyKoleosOptionsFlow(config_entry)

    def _schema(self, user_input: dict[str, Any] | None = None, *, reauth: bool = False) -> vol.Schema:
        """Return the simplified setup/reauth schema.

        The full ECARX/Gigya flow is still browser based. We intentionally do not
        collect the user's Renault password inside Home Assistant; the login stays
        on the official Renault/Gigya page and this integration only receives the
        short-lived redirect code.
        """
        user_input = user_input or {}
        return vol.Schema(
            {
                # Visible helper field. It is intentionally ignored by the backend;
                # it exists so the user has the exact URL to open/copy from the HA UI.
                vol.Optional(CONF_LOGIN_URL, default=user_input.get(CONF_LOGIN_URL) or gigya_login_url()): str,
                vol.Required(CONF_REDIRECT_URL_OR_CODE): str,
                vol.Required(CONF_COUNTRY_CODE, default=user_input.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE)): str,
            }
        )

    async def _login_and_build_entry_data(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], str]:
        user_input = dict(user_input)
        if CONF_AUTH_CODE not in user_input:
            user_input[CONF_AUTH_CODE] = _extract_auth_code(user_input.get(CONF_REDIRECT_URL_OR_CODE, ""))

        session = async_get_clientsession(self.hass)
        app_secret = (user_input.get(CONF_APP_SECRET) or DEFAULT_APP_SECRET).strip()
        device_identifier = (user_input.get(CONF_DEVICE_IDENTIFIER) or DEFAULT_DEVICE_IDENTIFIER).strip() or DEFAULT_DEVICE_IDENTIFIER
        api = MyKoleosApi(
            session,
            app_secret=app_secret,
            device_identifier=device_identifier,
        )
        auth_code = user_input[CONF_AUTH_CODE].strip()
        if not auth_code:
            raise MyKoleosAuthError("Missing redirect code")

        tokens = await api.login_with_code(
            auth_code,
            user_input[CONF_COUNTRY_CODE].strip() or DEFAULT_COUNTRY_CODE,
        )
        try:
            vehicle = await api.discover_vehicle(
                fallback_vin=(user_input.get(CONF_VIN) or "").strip() or None,
                fallback_model_code=(user_input.get(CONF_MODEL_CODE) or "").strip() or DEFAULT_MODEL_CODE,
            )
        except MyKoleosAuthError:
            if not (user_input.get(CONF_VIN) or "").strip():
                raise
            from .api import MyKoleosVehicle

            vehicle = MyKoleosVehicle(
                vin=user_input[CONF_VIN].strip(),
                model_code=(user_input.get(CONF_MODEL_CODE) or DEFAULT_MODEL_CODE).strip() or DEFAULT_MODEL_CODE,
            )

        data = {
            CONF_APP_SECRET: app_secret,
            CONF_DEVICE_IDENTIFIER: device_identifier,
            CONF_COUNTRY_CODE: user_input[CONF_COUNTRY_CODE].strip() or DEFAULT_COUNTRY_CODE,
            CONF_IDLE_SCAN_INTERVAL: max(
                int(user_input.get(CONF_IDLE_SCAN_INTERVAL, int(DEFAULT_IDLE_SCAN_INTERVAL.total_seconds()))),
                MIN_SCAN_INTERVAL_SECONDS,
            ),
            CONF_ACTIVE_SCAN_INTERVAL: max(
                int(user_input.get(CONF_ACTIVE_SCAN_INTERVAL, int(DEFAULT_ACTIVE_SCAN_INTERVAL.total_seconds()))),
                MIN_SCAN_INTERVAL_SECONDS,
            ),
            CONF_ADAPTIVE_POLLING: bool(user_input.get(CONF_ADAPTIVE_POLLING, DEFAULT_ADAPTIVE_POLLING)),
            CONF_UPDATE_SESSION_ON_POLL: bool(user_input.get(CONF_UPDATE_SESSION_ON_POLL, DEFAULT_UPDATE_SESSION_ON_POLL)),
            CONF_USER_ID: tokens.user_id,
            CONF_CLIENT_ID: tokens.client_id,
            CONF_ACCESS_TOKEN: tokens.access_token,
            CONF_REFRESH_TOKEN: tokens.refresh_token,
            CONF_EXPIRES_AT: tokens.expires_at,
            CONF_LATAM_AUTH_TOKEN: api.latam_auth_token,
            CONF_LATAM_USER_ID: api.latam_user_id,
            CONF_VIN: vehicle.vin,
            CONF_MODEL_CODE: vehicle.model_code or DEFAULT_MODEL_CODE,
        }
        return data, vehicle.vin

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step.

        Allow multiple entries. This is useful while reverse-engineering the LATAM
        command layer because an already working entry keeps entities/services loaded
        while a second entry can be used to obtain a fresh redirect code/token.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data, vin = await self._login_and_build_entry_data(user_input)
                same_vin_count = sum(
                    1
                    for entry in self._async_current_entries()
                    if entry.data.get(CONF_VIN) == vin
                )
                title = "Koleos"
                if same_vin_count:
                    instance_id = f"{vin}_{same_vin_count + 1}"
                    data[CONF_INSTANCE_ID] = instance_id
                    title = f"Koleos #{same_vin_count + 1}"
                return self.async_create_entry(title=title, data=data)
            except MyKoleosAuthError as err:
                _LOGGER.debug("Authentication failed during setup: %s", err)
                errors["base"] = "vin_missing" if "VIN" in str(err) else "invalid_auth"
            except MyKoleosConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during My Koleos setup")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(user_input),
            errors=errors,
            description_placeholders={"login_url": gigya_login_url()},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Start reauthentication flow."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Refresh tokens after the user provides a new redirect code."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is not None:
            merged = dict(entry.data)
            merged.update(user_input)
            try:
                data, _vin = await self._login_and_build_entry_data(merged)
                new_data = dict(entry.data)
                new_data.update(
                    {
                        CONF_ACCESS_TOKEN: data[CONF_ACCESS_TOKEN],
                        CONF_REFRESH_TOKEN: data[CONF_REFRESH_TOKEN],
                        CONF_EXPIRES_AT: data[CONF_EXPIRES_AT],
                        CONF_USER_ID: data[CONF_USER_ID],
                        CONF_CLIENT_ID: data[CONF_CLIENT_ID],
                        CONF_LATAM_AUTH_TOKEN: data.get(CONF_LATAM_AUTH_TOKEN),
                        CONF_LATAM_USER_ID: data.get(CONF_LATAM_USER_ID),
                    }
                )
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except MyKoleosAuthError:
                errors["base"] = "invalid_auth"
            except MyKoleosConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during My Koleos reauth")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._schema(entry.data, reauth=True),
            errors=errors,
            description_placeholders={"login_url": gigya_login_url()},
        )


class MyKoleosOptionsFlow(config_entries.OptionsFlow):
    """Handle options for My Koleos LATAM.

    Home Assistant changed OptionsFlow internals across recent releases.
    Keep the entry in a private attribute instead of assigning to
    self.config_entry directly, because in newer HA versions that name may
    be a read-only property managed by the framework.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        self._config_entry = config_entry

    def _entry(self) -> config_entries.ConfigEntry:
        entry = getattr(self, "config_entry", None) or self._config_entry
        if entry is None:
            raise RuntimeError("Config entry unavailable for options flow")
        return entry

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y", "sim"}
        return bool(value)

    @staticmethod
    def _as_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 3600) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = int(default)
        return min(max(number, minimum), maximum)

    def _option(self, key: str, default: Any) -> Any:
        entry = self._entry()
        return entry.options.get(key, entry.data.get(key, default))

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_IDLE_SCAN_INTERVAL: self._as_int(
                        user_input.get(CONF_IDLE_SCAN_INTERVAL),
                        int(DEFAULT_IDLE_SCAN_INTERVAL.total_seconds()),
                        minimum=MIN_SCAN_INTERVAL_SECONDS,
                    ),
                    CONF_ACTIVE_SCAN_INTERVAL: self._as_int(
                        user_input.get(CONF_ACTIVE_SCAN_INTERVAL),
                        int(DEFAULT_ACTIVE_SCAN_INTERVAL.total_seconds()),
                        minimum=MIN_SCAN_INTERVAL_SECONDS,
                    ),
                    CONF_ADAPTIVE_POLLING: self._as_bool(user_input.get(CONF_ADAPTIVE_POLLING), DEFAULT_ADAPTIVE_POLLING),
                    CONF_UPDATE_SESSION_ON_POLL: self._as_bool(
                        user_input.get(CONF_UPDATE_SESSION_ON_POLL),
                        DEFAULT_UPDATE_SESSION_ON_POLL,
                    ),
                    CONF_ENABLE_REMOTE_COMMANDS: self._as_bool(
                        user_input.get(CONF_ENABLE_REMOTE_COMMANDS),
                        DEFAULT_ENABLE_REMOTE_COMMANDS,
                    ),
                    CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS: self._as_bool(
                        user_input.get(CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS),
                        DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS,
                    ),
                    CONF_REMOTE_COMMAND_COOLDOWN: self._as_int(
                        user_input.get(CONF_REMOTE_COMMAND_COOLDOWN),
                        DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS,
                        minimum=0,
                    ),
                },
            )

        current_idle = self._as_int(
            self._option(CONF_IDLE_SCAN_INTERVAL, int(DEFAULT_IDLE_SCAN_INTERVAL.total_seconds())),
            int(DEFAULT_IDLE_SCAN_INTERVAL.total_seconds()),
            minimum=MIN_SCAN_INTERVAL_SECONDS,
        )
        current_active = self._as_int(
            self._option(CONF_ACTIVE_SCAN_INTERVAL, int(DEFAULT_ACTIVE_SCAN_INTERVAL.total_seconds())),
            int(DEFAULT_ACTIVE_SCAN_INTERVAL.total_seconds()),
            minimum=MIN_SCAN_INTERVAL_SECONDS,
        )
        current_adaptive = self._as_bool(
            self._option(CONF_ADAPTIVE_POLLING, DEFAULT_ADAPTIVE_POLLING),
            DEFAULT_ADAPTIVE_POLLING,
        )
        current_update_session = self._as_bool(
            self._option(CONF_UPDATE_SESSION_ON_POLL, DEFAULT_UPDATE_SESSION_ON_POLL),
            DEFAULT_UPDATE_SESSION_ON_POLL,
        )
        current_remote = self._as_bool(
            self._option(CONF_ENABLE_REMOTE_COMMANDS, DEFAULT_ENABLE_REMOTE_COMMANDS),
            DEFAULT_ENABLE_REMOTE_COMMANDS,
        )
        current_sensitive = self._as_bool(
            self._option(CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS, DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS),
            DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS,
        )
        current_cooldown = self._as_int(
            self._option(CONF_REMOTE_COMMAND_COOLDOWN, DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS),
            DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS,
            minimum=0,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADAPTIVE_POLLING, default=current_adaptive): bool,
                    vol.Required(CONF_ACTIVE_SCAN_INTERVAL, default=current_active): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=3600)
                    ),
                    vol.Required(CONF_IDLE_SCAN_INTERVAL, default=current_idle): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=3600)
                    ),
                    vol.Required(CONF_UPDATE_SESSION_ON_POLL, default=current_update_session): bool,
                    vol.Required(CONF_ENABLE_REMOTE_COMMANDS, default=current_remote): bool,
                    vol.Required(CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS, default=current_sensitive): bool,
                    vol.Required(CONF_REMOTE_COMMAND_COOLDOWN, default=current_cooldown): vol.All(
                        int, vol.Range(min=0, max=3600)
                    ),
                }
            ),
        )
