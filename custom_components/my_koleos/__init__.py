"""My Koleos LATAM integration."""

from __future__ import annotations

from datetime import timedelta
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlparse, unquote

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MyKoleosApi, MyKoleosError, MyKoleosAuthError, MyKoleosConnectionError, MyKoleosTokens, MyKoleosVehicle, REMOTE_PROXY_COMMANDS, recursive_find_value, gigya_login_url
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACTIVE_SCAN_INTERVAL,
    CONF_ADAPTIVE_POLLING,
    CONF_APP_SECRET,
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
    CONF_MODEL_CODE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_UPDATE_SESSION_ON_POLL,
    CONF_USER_ID,
    CONF_VIN,
    DEFAULT_ACTIVE_SCAN_INTERVAL,
    DEFAULT_ADAPTIVE_POLLING,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_CLIMATE_TEMPERATURE,
    DEFAULT_CLIMATE_DURATION_MINUTES,
    DEFAULT_DEVICE_IDENTIFIER,
    DEFAULT_ENABLE_REMOTE_COMMANDS,
    DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS,
    DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS,
    DEFAULT_IDLE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UPDATE_SESSION_ON_POLL,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    PLATFORMS,
)
from .coordinator import MyKoleosCoordinator


MyKoleosConfigEntry = ConfigEntry

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_PROXY_COMMAND = "send_proxy_command"
SERVICE_REMOTE_COMMAND = "remote_command"
SERVICE_LATAM_LOGIN_CODE = "latam_login_code"
SERVICE_CREATE_LOGIN_URL = "create_login_url"
SERVICE_DEBUG_ENTRIES = "debug_entries"
SERVICE_CLIMATE_START = "climate_start"
SERVICE_CLIMATE_STOP = "climate_stop"

DATA_COORDINATORS = "coordinators"
DATA_SERVICES_REGISTERED = "services_registered"

REMOTE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("command"): vol.In(sorted(REMOTE_PROXY_COMMANDS.keys())),
        vol.Optional("payload", default={}): dict,
        vol.Optional("method"): str,
        vol.Optional("backend", default="auto"): vol.In(["auto", "latam_auto", "latam", "latam_rest", "latam_web", "ecarx"]),
        vol.Optional("merge_defaults", default=True): bool,
        vol.Optional("vin"): str,
        vol.Optional("entry_id"): str,
    }
)

RAW_PROXY_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("endpoint"): str,
        vol.Optional("payload", default={}): dict,
        vol.Optional("method", default="POST"): str,
        vol.Optional("backend", default="auto"): vol.In(["auto", "latam_auto", "latam", "latam_rest", "latam_web", "ecarx"]),
        vol.Optional("merge_defaults", default=True): bool,
        vol.Optional("vin"): str,
        vol.Optional("entry_id"): str,
    }
)

LATAM_LOGIN_CODE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("redirect_url_or_code"): str,
        vol.Optional("country_code", default=DEFAULT_COUNTRY_CODE): str,
        vol.Optional("vin"): str,
        vol.Optional("entry_id"): str,
    }
)

CREATE_LOGIN_URL_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("ui_locales", default="pt-BR"): str,
    }
)

DEBUG_ENTRIES_SERVICE_SCHEMA = vol.Schema({})

CLIMATE_START_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature", default=DEFAULT_CLIMATE_TEMPERATURE): vol.Coerce(int),
        vol.Optional("minutes", default=DEFAULT_CLIMATE_DURATION_MINUTES): vol.Coerce(int),
        vol.Optional("vin"): str,
        vol.Optional("entry_id"): str,
    }
)

CLIMATE_STOP_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("vin"): str,
        vol.Optional("entry_id"): str,
    }
)


def _extract_auth_code(value: str) -> str:
    """Extract OAuth code from either a raw code or full redirect URL."""
    value = (value or "").strip().strip('\"\'')
    if not value:
        return ""
    value = value.replace("&amp;", "&")

    # Prefer a raw extraction so OAuth codes containing literal plus signs are not
    # converted to spaces by parse_qs/unquote_plus.
    marker = "code="
    if marker in value:
        raw = value.split(marker, 1)[1]
        for sep in ("&", "#"):
            raw = raw.split(sep, 1)[0]
        return unquote(raw).strip()

    parsed = urlparse(value.replace("#", "?"))
    query = parse_qs(parsed.query)
    code_values = query.get("code")
    if code_values and code_values[0]:
        return code_values[0].strip()
    return value


def _looks_like_placeholder_or_invalid_code(raw_value: str, auth_code: str) -> str | None:
    """Return a user-facing validation error if the provided value is clearly invalid."""
    raw_upper = (raw_value or "").upper()
    code = (auth_code or "").strip()
    code_upper = code.upper()
    placeholder_markers = (
        "COLE_A_URL",
        "COLE A URL",
        "APENAS_O_CODE",
        "CODE_AQUI",
        "CODE=...",
        "<CODE",
        "SEU_CODE",
    )
    if any(marker in raw_upper or marker in code_upper for marker in placeholder_markers):
        return (
            "Você enviou o texto de exemplo/placeholder. Abra a URL de login, faça login e cole "
            "a URL final real contendo /latamRedirect?code=... ou somente o valor real do code=."
        )
    if raw_value.strip().lower().startswith(("http://", "https://")) and "code=" not in raw_value:
        return "A URL informada não contém code=. Cole a URL final após o login, não a URL inicial de login."
    if " " in code or "\n" in code or "\r" in code:
        return "O code extraído contém espaços/quebras de linha. Copie novamente a URL final ou apenas o valor completo de code=."
    if len(code) < 20:
        return "O code informado parece curto demais. Gere um code= novo no navegador e cole a URL final completa."
    return None


def _entry_int(entry: ConfigEntry, key: str, default: int) -> int:
    return int(entry.options.get(key, entry.data.get(key, default)))


def _entry_bool(entry: ConfigEntry, key: str, default: bool) -> bool:
    return bool(entry.options.get(key, entry.data.get(key, default)))


async def async_setup_entry(hass: HomeAssistant, entry: MyKoleosConfigEntry) -> bool:
    """Set up My Koleos LATAM from a config entry."""
    session = async_get_clientsession(hass)
    tokens = MyKoleosTokens(
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        user_id=entry.data[CONF_USER_ID],
        client_id=entry.data[CONF_CLIENT_ID],
        expires_at=entry.data.get(CONF_EXPIRES_AT),
    )
    vehicle = MyKoleosVehicle(
        vin=entry.data[CONF_VIN],
        model_code=entry.data.get(CONF_MODEL_CODE) or "R745",
    )
    api = MyKoleosApi(
        session,
        app_secret=entry.data[CONF_APP_SECRET],
        device_identifier=entry.data.get(CONF_DEVICE_IDENTIFIER, DEFAULT_DEVICE_IDENTIFIER),
        tokens=tokens,
        vehicle=vehicle,
        latam_auth_token=entry.data.get(CONF_LATAM_AUTH_TOKEN),
        latam_user_id=entry.data.get(CONF_LATAM_USER_ID),
    )

    legacy_scan_seconds = int(DEFAULT_SCAN_INTERVAL.total_seconds())
    idle_seconds = _entry_int(
        entry,
        CONF_IDLE_SCAN_INTERVAL,
        int(entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, legacy_scan_seconds))),
    )
    active_seconds = _entry_int(entry, CONF_ACTIVE_SCAN_INTERVAL, int(DEFAULT_ACTIVE_SCAN_INTERVAL.total_seconds()))
    idle_seconds = max(idle_seconds, MIN_SCAN_INTERVAL_SECONDS)
    active_seconds = max(active_seconds, MIN_SCAN_INTERVAL_SECONDS)

    coordinator = MyKoleosCoordinator(
        hass,
        entry,
        api,
        idle_interval=timedelta(seconds=idle_seconds),
        active_interval=timedelta(seconds=active_seconds),
        adaptive_polling=_entry_bool(entry, CONF_ADAPTIVE_POLLING, DEFAULT_ADAPTIVE_POLLING),
        update_session_on_poll=_entry_bool(entry, CONF_UPDATE_SESSION_ON_POLL, DEFAULT_UPDATE_SESSION_ON_POLL),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_COORDINATORS, {})[entry.entry_id] = coordinator
    _register_remote_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: MyKoleosConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _entry_option_bool(entry: ConfigEntry, key: str, default: bool) -> bool:
    return bool(entry.options.get(key, entry.data.get(key, default)))


def _entry_option_int(entry: ConfigEntry, key: str, default: int) -> int:
    return int(entry.options.get(key, entry.data.get(key, default)))


def _remote_commands_enabled(entry: ConfigEntry) -> bool:
    return _entry_option_bool(entry, CONF_ENABLE_REMOTE_COMMANDS, DEFAULT_ENABLE_REMOTE_COMMANDS)


def _sensitive_remote_commands_enabled(entry: ConfigEntry) -> bool:
    return _entry_option_bool(entry, CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS, DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS)


def _loaded_coordinators(hass: HomeAssistant) -> dict[str, MyKoleosCoordinator]:
    """Return loaded coordinators indexed by config entry id."""
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_COORDINATORS, {})


def _select_coordinator(hass: HomeAssistant, call_data: dict[str, Any]) -> MyKoleosCoordinator:
    """Select the target coordinator for a service call."""
    coordinators = _loaded_coordinators(hass)
    if not coordinators:
        raise HomeAssistantError("Nenhuma entrada My Koleos LATAM carregada.")

    entry_id = str(call_data.get("entry_id") or "").strip()
    if entry_id:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise HomeAssistantError(f"entry_id não encontrado para My Koleos LATAM: {entry_id}")
        return coordinator

    vin = str(call_data.get("vin") or "").strip().upper()
    if vin:
        matches = [coord for coord in coordinators.values() if (coord.api.vin or "").upper() == vin]
        if not matches:
            raise HomeAssistantError(f"VIN não encontrado em entradas My Koleos LATAM carregadas: {vin}")
        if len(matches) > 1:
            _LOGGER.warning(
                "Multiple My Koleos entries match VIN %s; using the first loaded entry. Provide entry_id to force a specific hub.",
                vin,
            )
        return matches[0]

    if len(coordinators) == 1:
        return next(iter(coordinators.values()))

    vins = ", ".join(
        f"{coord.api.vin or 'sem VIN'} ({entry_id})" for entry_id, coord in coordinators.items()
    )
    raise HomeAssistantError(
        "Há múltiplas entradas My Koleos LATAM carregadas; informe vin ou entry_id na chamada. "
        f"Entradas: {vins}"
    )



async def _notify(hass: HomeAssistant, title: str, message: str) -> None:
    """Create a persistent notification if the integration is available."""
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": title, "message": message},
        blocking=False,
    )


def _masked_present(value: str | None) -> str:
    if not value:
        return "não"
    return f"sim ({len(value)} caracteres)"


def _entries_debug_message(hass: HomeAssistant) -> str:
    lines = ["Entradas My Koleos LATAM carregadas:", ""]
    coordinators = _loaded_coordinators(hass)
    if not coordinators:
        return "Nenhuma entrada My Koleos LATAM carregada."
    for entry_id, coord in coordinators.items():
        entry = coord.entry
        lines.extend(
            [
                f"- title: {entry.title}",
                f"  entry_id: `{entry_id}`",
                f"  vin: `{coord.api.vin or entry.data.get(CONF_VIN, '')}`",
                f"  remote_enabled: {_remote_commands_enabled(entry)}",
                f"  sensitive_enabled: {_sensitive_remote_commands_enabled(entry)}",
                f"  latam_auth_token: {_masked_present(coord.api.latam_auth_token or entry.data.get(CONF_LATAM_AUTH_TOKEN))}",
                f"  latam_user_id: `{coord.api.latam_user_id or entry.data.get(CONF_LATAM_USER_ID, '')}`",
                "",
            ]
        )
    lines.append("Use exatamente o entry_id acima nos serviços de login e comando para evitar escolher o hub errado.")
    return "\n".join(lines)

def _register_remote_services(hass: HomeAssistant) -> None:
    """Register global remote-command test services once, routed to an entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_SERVICES_REGISTERED):
        return
    domain_data[DATA_SERVICES_REGISTERED] = True

    async def _execute(call: ServiceCall, command: str, payload: dict[str, Any], *, method: str | None = None, backend: str = "auto", endpoint: str | None = None, merge_defaults: bool = True) -> None:
        coordinator = _select_coordinator(hass, dict(call.data))
        entry = coordinator.entry
        if not _remote_commands_enabled(entry):
            raise HomeAssistantError("Comandos remotos estão desativados no hub selecionado. Ative nas opções da integração.")
        definition = REMOTE_PROXY_COMMANDS.get(command, {})
        if definition.get("sensitive") and not _sensitive_remote_commands_enabled(entry):
            raise HomeAssistantError("Comando remoto sensível bloqueado no hub selecionado. Ative 'Permitir comandos sensíveis' nas opções.")
        cooldown = _entry_option_int(entry, CONF_REMOTE_COMMAND_COOLDOWN, DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS)
        now = time.monotonic()
        last = getattr(coordinator, "_last_remote_command_monotonic", 0.0)
        if cooldown > 0 and now - last < cooldown:
            raise HomeAssistantError(f"Cooldown de comando remoto ativo; aguarde {int(cooldown - (now - last)) + 1}s.")
        try:
            result = await coordinator.async_send_remote_command(
                command,
                payload=payload,
                method=method,
                backend=backend,
                path=endpoint,
                merge_defaults=merge_defaults,
            )
            _LOGGER.warning(
                "My Koleos remote command %s sent via %s for VIN %s; response=%s",
                command,
                backend,
                coordinator.api.vin,
                result,
            )
        except MyKoleosError as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def handle_named(call: ServiceCall) -> None:
        await _execute(
            call,
            call.data["command"],
            dict(call.data.get("payload") or {}),
            method=call.data.get("method"),
            backend=call.data.get("backend", "auto"),
            merge_defaults=bool(call.data.get("merge_defaults", True)),
        )

    async def handle_raw(call: ServiceCall) -> None:
        endpoint = str(call.data["endpoint"]).strip()
        await _execute(
            call,
            "raw",
            dict(call.data.get("payload") or {}),
            method=str(call.data.get("method", "POST")).upper(),
            backend=call.data.get("backend", "auto"),
            endpoint=endpoint,
            merge_defaults=bool(call.data.get("merge_defaults", True)),
        )

    async def handle_climate_start(call: ServiceCall) -> None:
        await _execute(
            call,
            "hvac_start",
            {"temperature": int(call.data.get("temperature", DEFAULT_CLIMATE_TEMPERATURE)), "minutes": int(call.data.get("minutes", DEFAULT_CLIMATE_DURATION_MINUTES))},
            method="PUT",
            backend="ecarx",
            merge_defaults=False,
        )

    async def handle_climate_stop(call: ServiceCall) -> None:
        await _execute(
            call,
            "hvac_stop",
            {},
            method="PUT",
            backend="ecarx",
            merge_defaults=False,
        )

    async def handle_latam_login_code(call: ServiceCall) -> None:
        coordinator = _select_coordinator(hass, dict(call.data))
        entry = coordinator.entry
        raw_code = str(call.data["redirect_url_or_code"])
        auth_code = _extract_auth_code(raw_code)
        if not auth_code:
            raise HomeAssistantError("Informe a URL de redirecionamento completa ou o valor do parâmetro code=.")
        invalid_reason = _looks_like_placeholder_or_invalid_code(raw_code, auth_code)
        if invalid_reason:
            raise HomeAssistantError(invalid_reason)
        country_code = str(call.data.get("country_code") or entry.data.get(CONF_COUNTRY_CODE) or DEFAULT_COUNTRY_CODE)
        try:
            data = await coordinator.api.latam_login_code(auth_code, country_code)
            latam_auth = recursive_find_value(data, "authToken")
            latam_user = recursive_find_value(data, "userid") or recursive_find_value(data, "userId")
            tsp_auth_code = recursive_find_value(data, "tspAuthCode")
            if not latam_auth:
                raise MyKoleosAuthError("Resposta LATAM sem authToken; gere um code= novo e tente novamente.")
            coordinator.api.latam_auth_token = str(latam_auth)
            if latam_user:
                coordinator.api.latam_user_id = str(latam_user)
            new_data = dict(entry.data)
            new_data[CONF_LATAM_AUTH_TOKEN] = str(latam_auth)
            if latam_user:
                new_data[CONF_LATAM_USER_ID] = str(latam_user)
            # Store tspAuthCode only for diagnostics/future reauth help; do not log it.
            if tsp_auth_code:
                new_data["tsp_auth_code_last_seen"] = str(tsp_auth_code)
            hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.warning(
                "My Koleos LATAM authToken updated via service for VIN %s; remote commands can be tested again.",
                coordinator.api.vin,
            )
        except MyKoleosAuthError as exc:
            raise HomeAssistantError(str(exc)) from exc
        except MyKoleosConnectionError as exc:
            raise HomeAssistantError(str(exc)) from exc
        except MyKoleosError as exc:
            raise HomeAssistantError(str(exc)) from exc


    async def handle_create_login_url(call: ServiceCall) -> None:
        url = gigya_login_url(str(call.data.get("ui_locales") or "pt-BR"))
        await _notify(
            hass,
            "My Koleos LATAM - URL de login",
            "Abra a URL abaixo, faça login e copie a URL final que contém `/latamRedirect?code=...`.\n\n" + url,
        )

    async def handle_debug_entries(call: ServiceCall) -> None:
        await _notify(hass, "My Koleos LATAM - Entradas carregadas", _entries_debug_message(hass))

    hass.services.async_register(DOMAIN, SERVICE_REMOTE_COMMAND, handle_named, schema=REMOTE_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_PROXY_COMMAND, handle_raw, schema=RAW_PROXY_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLIMATE_START, handle_climate_start, schema=CLIMATE_START_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLIMATE_STOP, handle_climate_stop, schema=CLIMATE_STOP_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LATAM_LOGIN_CODE, handle_latam_login_code, schema=LATAM_LOGIN_CODE_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_LOGIN_URL, handle_create_login_url, schema=CREATE_LOGIN_URL_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DEBUG_ENTRIES, handle_debug_entries, schema=DEBUG_ENTRIES_SERVICE_SCHEMA)


async def async_unload_entry(hass: HomeAssistant, entry: MyKoleosConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinators = _loaded_coordinators(hass)
        coordinators.pop(entry.entry_id, None)
        if not coordinators and hass.data.get(DOMAIN, {}).get(DATA_SERVICES_REGISTERED):
            hass.services.async_remove(DOMAIN, SERVICE_REMOTE_COMMAND)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_PROXY_COMMAND)
            hass.services.async_remove(DOMAIN, SERVICE_CLIMATE_START)
            hass.services.async_remove(DOMAIN, SERVICE_CLIMATE_STOP)
            hass.services.async_remove(DOMAIN, SERVICE_LATAM_LOGIN_CODE)
            hass.services.async_remove(DOMAIN, SERVICE_CREATE_LOGIN_URL)
            hass.services.async_remove(DOMAIN, SERVICE_DEBUG_ENTRIES)
            hass.data[DOMAIN][DATA_SERVICES_REGISTERED] = False
    return unload_ok
