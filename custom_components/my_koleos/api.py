"""API client for My Koleos LATAM / ECARX TSP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import string
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from aiohttp import ClientError, ClientResponseError, ClientSession

_LOGGER = logging.getLogger(__name__)

from .const import (
    DEFAULT_APP_ID,
    DEFAULT_DEVICE_IDENTIFIER,
    DEFAULT_DEVICE_TYPE,
    DEFAULT_ENV,
    DEFAULT_HOST,
    DEFAULT_LANGUAGE,
    DEFAULT_CLIMATE_TEMPERATURE,
    DEFAULT_CLIMATE_DURATION_MINUTES,
    DEFAULT_LATAM_HOST,
    DEFAULT_LATAM_WEB_HOST,
    DEFAULT_MODEL_CODE,
    DEFAULT_OPERATOR,
    GIGYA_AUTH_BASE,
    GIGYA_CLIENT_ID,
    GIGYA_CODE_CHALLENGE,
    GIGYA_REDIRECT_URI,
    GIGYA_STATE,
)


class MyKoleosError(Exception):
    """Base error."""


class MyKoleosAuthError(MyKoleosError):
    """Authentication or token error."""


class MyKoleosConnectionError(MyKoleosError):
    """Network/server error."""


def mask(value: str | None, keep: int = 6) -> str:
    """Mask a sensitive value for logs."""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def recursive_find_value(data: Any, key: str) -> Any:
    """Find the first value for key in nested JSON."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = recursive_find_value(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find_value(item, key)
            if found is not None:
                return found
    return None


def recursive_find_vehicle(data: Any) -> dict[str, Any] | None:
    """Find a vehicle-like dict containing a VIN."""
    if isinstance(data, dict):
        vin = data.get("vin") or data.get("VIN")
        if isinstance(vin, str) and len(vin) >= 10:
            return data
        for value in data.values():
            found = recursive_find_vehicle(value)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find_vehicle(item)
            if found is not None:
                return found
    return None


def get_path(data: Any, path: str, default: Any = None) -> Any:
    """Get nested data by dotted path."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def to_float(value: Any) -> float | None:
    """Convert API numeric strings to float."""
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    """Convert API numeric strings to int."""
    if value in (None, "", "null"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def epoch_ms(value: Any) -> datetime | None:
    """Convert epoch milliseconds/seconds string to aware UTC datetime."""
    number = to_float(value)
    if number is None or number <= 0:
        return None
    if number > 3_600_000_000:
        number = number / 1000
    try:
        return datetime.fromtimestamp(number, UTC)
    except (OSError, ValueError, OverflowError):
        return None


def decode_position(value: Any) -> float | None:
    """Decode ECARX integer position fields."""
    number = to_float(value)
    if number is None:
        return None
    return number / 3_600_000


def encode_query(params: list[tuple[str, str]]) -> str:
    """Encode query like OkHttp/Retrofit did for the tested calls."""
    return "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in params)


def raw_query_pairs(query: str) -> list[tuple[str, str]]:
    if not query:
        return []
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if not part:
            continue
        key, value = part.split("=", 1) if "=" in part else (part, "")
        pairs.append((key, value))
    return pairs


def canonical_query_from_url(full_url: str) -> str:
    pairs = sorted(raw_query_pairs(urlsplit(full_url).query), key=lambda kv: kv[0])
    out = []
    for key, value in pairs:
        value = (
            value.replace("+", "%20")
            .replace("*", "%2A")
            .replace("%7E", "~")
            .replace(",", "%2C")
        )
        out.append(f"{key}={value}")
    return "&".join(out)


def canonical_path(full_url: str) -> str:
    return urlsplit(full_url).path or "/"


def canonical_headers(headers: dict[str, str]) -> str:
    out: list[str] = []
    for name in sorted(headers.keys()):
        if name.lower() == "accept":
            out.append(headers[name].strip())
    x_api = {name: value for name, value in headers.items() if name.startswith("X-api")}
    for name in sorted(x_api.keys()):
        out.append(f"{name.lower().strip()}:{x_api[name].strip()}")
    return "\n".join(out) + "\n" if out else ""


def body_md5_base64(body_text: str | None) -> str:
    digest = hashlib.md5((body_text or "").encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii") + "\n"


def sign_request(
    *,
    sign_secret: str,
    method: str,
    full_url: str,
    headers_before_signature: dict[str, str],
    body_text: str | None,
) -> tuple[str, str]:
    timestamp_ms = str(int(time.time() * 1000))
    canonical = (
        canonical_headers(headers_before_signature)
        + "\n"
        + canonical_query_from_url(full_url)
        + "\n"
        + body_md5_base64(body_text)
        + timestamp_ms
        + "\n"
        + method.upper()
        + "\n"
        + canonical_path(full_url)
    )
    digest = hmac.new(sign_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii").strip(), timestamp_ms


def random_alnum(n: int) -> str:
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def get_nonce() -> str:
    raw = str(uuid.uuid4()) + random_alnum(7) + str(int(time.time() * 1000))
    return raw[-36:] if len(raw) > 36 else raw


def json_compact(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def gigya_login_url(ui_locales: str = "pt-BR") -> str:
    query = [
        ("response_type", "code"),
        ("ui_locales", ui_locales),
        ("client_id", GIGYA_CLIENT_ID),
        ("redirect_uri", GIGYA_REDIRECT_URI),
        ("code_challenge_method", "S256"),
        ("code_challenge", GIGYA_CODE_CHALLENGE),
        ("scope", "openid email personId lang vehicle"),
        ("state", GIGYA_STATE),
        ("prompt", "login"),
    ]
    return GIGYA_AUTH_BASE + "?" + encode_query(query)


@dataclass
class MyKoleosTokens:
    access_token: str
    refresh_token: str
    user_id: str
    client_id: str
    expires_at: float | None = None


@dataclass
class MyKoleosVehicle:
    vin: str
    model_code: str


REMOTE_PROXY_COMMANDS: dict[str, dict[str, Any]] = {
    # Method/payload defaults are best-effort for the LATAM remote surfaces found in the app.
    # The APK contains legacy /api/1/proxy/... paths and newer /api/4/hcb/... paths.
    # Use send_proxy_command with explicit method/payload while validating each endpoint.
    "lock_status": {"path": "/api/1/proxy/lockStatus", "method": "POST", "sensitive": False, "payload": {}},
    "lock": {"path": "/api/1/proxy/lockUnlock", "method": "POST", "sensitive": True, "payload": {"action": "lock", "command": "lock", "lockStatus": "1", "lockUnlock": "lock"}},
    "unlock": {"path": "/api/1/proxy/lockUnlock", "method": "POST", "sensitive": True, "payload": {"action": "unlock", "command": "unlock", "lockStatus": "0", "lockUnlock": "unlock"}},
    "horn_lights": {"path": "/api/1/proxy/hornLights", "method": "POST", "sensitive": False, "payload": {"action": "start", "duration": 10}},
    "find_my_car": {"path": "/api/1/proxy/findMyCar", "method": "POST", "sensitive": False, "payload": {"action": "start"}},
    # Confirmed My Koleos LATAM / ECARX RCE_2 flow (com_ac_final):
    # PUT /remote-control/vehicle/telematics/{vin}
    # serviceParameters use serialized enum values, not enum names: rce.temp / rce.conditioner.
    "hvac_start": {"path": "/remote-control/vehicle/telematics/{vin}", "method": "PUT", "backend": "ecarx", "sensitive": False, "payload": {"temperature": DEFAULT_CLIMATE_TEMPERATURE, "minutes": DEFAULT_CLIMATE_DURATION_MINUTES}},
    "hvac_stop": {"path": "/remote-control/vehicle/telematics/{vin}", "method": "PUT", "backend": "ecarx", "sensitive": False, "payload": {}},
    "hvac_schedule": {"path": "/api/1/proxy/hvacSchedule", "method": "POST", "sensitive": False, "payload": {}},
    "update_hvac_schedule": {"path": "/api/1/proxy/updateHvacSchedule", "method": "POST", "sensitive": False, "payload": {}},
    "engine_start": {"path": "/api/1/proxy/engineStart", "method": "POST", "sensitive": True, "payload": {"action": "start", "engineStatus": "1"}},
    "engine_stop": {"path": "/api/1/proxy/engineStart", "method": "POST", "sensitive": True, "payload": {"action": "stop", "engineStatus": "0"}},
    "res_state": {"path": "/api/1/proxy/resState", "method": "POST", "sensitive": False, "payload": {}},
    "cockpit": {"path": "/api/1/proxy/cockpit", "method": "POST", "sensitive": False, "payload": {}},
    "long_poll": {"path": "/api/1/proxy/longPoll", "method": "POST", "sensitive": False, "payload": {}},
    "charge_start": {"path": "/api/1/proxy/chargeStart", "method": "POST", "sensitive": False, "payload": {"action": "start"}},
    "charge_schedule": {"path": "/api/1/proxy/chargeSchedule", "method": "POST", "sensitive": False, "payload": {}},
    "update_charge_schedule": {"path": "/api/1/proxy/updateChargeSchedule", "method": "POST", "sensitive": False, "payload": {}},
    "srp_initiates": {"path": "/api/1/proxy/srpInitiates", "method": "POST", "sensitive": True, "payload": {}},
    "srp_sets": {"path": "/api/1/proxy/srpSets", "method": "POST", "sensitive": True, "payload": {}},
    "unpairing_app": {"path": "/api/1/proxy/unpairingApp", "method": "POST", "sensitive": True, "payload": {}},

    # Newer HCB paths present in the same decompiled constants file. These are useful
    # for discovering which remote surface is live in LATAM production.
    "hcb_settings": {"path": "/api/4/hcb/settings", "method": "GET", "sensitive": False, "payload": {}},
    "hcb_soc_levels": {"path": "/api/4/hcb/soc-levels", "method": "GET", "sensitive": False, "payload": {}},
    "hcb_horn_lights": {"path": "/api/4/hcb/horn-lights", "method": "POST", "sensitive": False, "payload": {"action": "start", "duration": 10}},
    "hcb_lock": {"path": "/api/4/hcb/lock-unlock", "method": "POST", "sensitive": True, "payload": {"action": "lock", "command": "lock", "lockStatus": "1", "lockUnlock": "lock"}},
    "hcb_unlock": {"path": "/api/4/hcb/lock-unlock", "method": "POST", "sensitive": True, "payload": {"action": "unlock", "command": "unlock", "lockStatus": "0", "lockUnlock": "unlock"}},

    # ECARX read-only status routes confirmed in the SDK Retrofit interface.
    # These are not physical actions; they are useful as safe diagnostics for res_state.
    "ecarx_status": {"path": "/remote-control/vehicle/status/{vin}", "method": "GET", "sensitive": False, "payload": {}},
    "ecarx_state": {"path": "/remote-control/vehicle/status/state/{vin}", "method": "GET", "sensitive": False, "payload": {}},
}


# These endpoints look like state/status reads in the APK constants.
# While mapping the real backend, try GET as a fallback if POST returns 404/405.
REMOTE_READ_COMMANDS = {"lock_status", "res_state", "cockpit", "long_poll", "hcb_settings", "hcb_soc_levels", "ecarx_status", "ecarx_state"}


# Named-command route aliases. We only add safe/read-only aliases automatically except
# for explicit commands whose name already implies the same physical effect.
REMOTE_ROUTE_ALIASES: dict[str, list[dict[str, Any]]] = {
    "res_state": [
        {"path": "/api/4/hcb/settings", "method": "GET", "payload": {}},
        {"path": "/api/4/hcb/soc-levels", "method": "GET", "payload": {}},
    ],
    "lock_status": [
        {"path": "/api/4/hcb/settings", "method": "GET", "payload": {}},
    ],
    "horn_lights": [
        {"path": "/api/4/hcb/horn-lights", "method": "POST", "payload": {"action": "start", "duration": 10}},
    ],
    "lock": [
        {"path": "/api/4/hcb/lock-unlock", "method": "POST", "payload": {"action": "lock", "command": "lock", "lockStatus": "1", "lockUnlock": "lock"}},
    ],
    "unlock": [
        {"path": "/api/4/hcb/lock-unlock", "method": "POST", "payload": {"action": "unlock", "command": "unlock", "lockStatus": "0", "lockUnlock": "unlock"}},
    ],
}


class MyKoleosApi:
    """Minimal read-only API wrapper for My Koleos LATAM / ECARX."""

    def __init__(
        self,
        session: ClientSession,
        *,
        app_secret: str,
        device_identifier: str = DEFAULT_DEVICE_IDENTIFIER,
        base_host: str = DEFAULT_HOST,
        latam_host: str = DEFAULT_LATAM_HOST,
        operator: str = DEFAULT_OPERATOR,
        app_id: str = DEFAULT_APP_ID,
        env_type: str = DEFAULT_ENV,
        language: str = DEFAULT_LANGUAGE,
        device_type: str = DEFAULT_DEVICE_TYPE,
        tokens: MyKoleosTokens | None = None,
        vehicle: MyKoleosVehicle | None = None,
        latam_auth_token: str | None = None,
        latam_user_id: str | None = None,
    ) -> None:
        self.session = session
        self.app_secret = app_secret
        self.device_identifier = device_identifier or DEFAULT_DEVICE_IDENTIFIER
        self.base_host = base_host.rstrip("/")
        self.latam_host = latam_host.rstrip("/")
        self.operator = operator
        self.app_id = app_id
        self.env_type = env_type
        self.language = language
        self.device_type = device_type
        self.tokens = tokens
        self.vehicle = vehicle
        self.latam_auth_token = latam_auth_token
        self.latam_user_id = latam_user_id

    @property
    def access_token(self) -> str | None:
        return self.tokens.access_token if self.tokens else None

    @property
    def refresh_token(self) -> str | None:
        return self.tokens.refresh_token if self.tokens else None

    @property
    def user_id(self) -> str | None:
        return self.tokens.user_id if self.tokens else None

    @property
    def client_id(self) -> str | None:
        return self.tokens.client_id if self.tokens else None

    @property
    def vin(self) -> str | None:
        return self.vehicle.vin if self.vehicle else None

    @property
    def model_code(self) -> str | None:
        return self.vehicle.model_code if self.vehicle else None

    def _needs_vehicle_headers(self, path: str) -> bool:
        return not ("/geelyTCAccess/tcservices/capability/" in path or "/user/session/update" in path)

    def _build_headers(self, *, path: str, include_auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-APP-ID": self.app_id,
            "Accept": "application/json",
            "Connection": "close",
            "X-AGENT-TYPE": "ANDROID",
            "X-DEVICE-TYPE": self.device_type or "mobile",
            "X-OPERATOR-CODE": self.operator,
            "X-DEVICE-IDENTIFIER": self.device_identifier,
            "X-ENV-TYPE": self.env_type,
            "Accept-Encoding": "identity",
            "X-VERSION": f"{self.operator.lower()}New",
            "Accept-Language": self.language,
            "Content-Type": "application/json; charset=utf-8",
            "X-api-signature-version": "1.0",
            "X-api-signature-nonce": get_nonce(),
        }
        if include_auth and self.access_token:
            headers["Authorization"] = self.access_token
        if include_auth and self.client_id:
            headers["X-CLIENT-ID"] = self.client_id
        elif not self.client_id:
            headers.update(
                {
                    "X-DEVICE-MANUFACTURE": "Google",
                    "X-DEVICE-BRAND": "Android",
                    "X-DEVICE-MODEL": "Android",
                    "X-DEVICE-RELEASE-DATE": "",
                    "X-AGENT-VERSION": "14",
                }
            )
        if self.vin and self.model_code and self._needs_vehicle_headers(path):
            headers["X-VEHICLE-SERIES"] = self.model_code
            headers["X-VEHICLE-MODEL"] = self.model_code
            headers["X-Vehicle-IDENTIFIER"] = self.vin
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, Any] | None = None,
        include_auth: bool = True,
    ) -> Any:
        query = query or []
        query_string = encode_query(query)
        url = self.base_host + path + (f"?{query_string}" if query_string else "")
        body_text = json_compact(body) if body is not None else None
        headers = self._build_headers(path=path, include_auth=include_auth)
        signature, timestamp = sign_request(
            sign_secret=self.app_secret,
            method=method,
            full_url=url,
            headers_before_signature=headers,
            body_text=body_text,
        )
        headers["X-SIGNATURE"] = signature
        headers["X-TIMESTAMP"] = timestamp
        try:
            async with self.session.request(
                method.upper(),
                url,
                headers=headers,
                data=body_text.encode("utf-8") if body_text is not None else None,
                timeout=30,
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {"raw": text}
                if resp.status in (401, 403):
                    raise MyKoleosAuthError(f"HTTP {resp.status}: {data}")
                if resp.status >= 400:
                    raise MyKoleosConnectionError(f"HTTP {resp.status}: {data}")
                return data
        except MyKoleosError:
            raise
        except (ClientError, TimeoutError, ClientResponseError) as exc:
            raise MyKoleosConnectionError(str(exc)) from exc

    async def latam_login_code(self, auth_code: str, country_code: str) -> dict[str, Any]:
        body = {"token": auth_code, "countryCode": country_code, "autoLoginChecked": "Y"}
        url = self.latam_host + "/api/4/auth/login"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Language": self.language,
            "User-Agent": "okhttp/4.12.0",
        }
        try:
            async with self.session.post(url, headers=headers, data=json_compact(body).encode("utf-8"), timeout=30) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {"raw": text}
                if resp.status in (401, 403):
                    raise MyKoleosAuthError(f"HTTP {resp.status}: {data}")
                if resp.status >= 400:
                    if resp.status == 500:
                        raise MyKoleosAuthError(
                            "HTTP 500 em /api/4/auth/login. Para esse endpoint, normalmente significa "
                            "code= inválido, expirado ou já usado. Gere um code= novo abrindo a URL de login "
                            "em uma aba nova, faça login e cole a URL final /latamRedirect?code=... sem abrir o app antes. "
                            f"Resposta: {data}"
                        )
                    raise MyKoleosConnectionError(f"HTTP {resp.status}: {data}")
                return data
        except MyKoleosError:
            raise
        except (ClientError, TimeoutError, ClientResponseError) as exc:
            raise MyKoleosConnectionError(str(exc)) from exc

    async def ecarx_login_authcode(self, tsp_auth_code: str) -> MyKoleosTokens:
        data = await self._request(
            "POST",
            "/auth/account/session/secure",
            query=[("identity_type", "renault")],
            body={"authCode": tsp_auth_code},
            include_auth=False,
        )
        access = recursive_find_value(data, "accessToken")
        refresh = recursive_find_value(data, "refreshToken")
        user_id = recursive_find_value(data, "userId") or recursive_find_value(data, "userid")
        client_id = recursive_find_value(data, "clientId")
        expires_in = to_int(recursive_find_value(data, "expiresIn")) or 7200
        if not access or not refresh or not user_id or not client_id:
            raise MyKoleosAuthError(f"Resposta de login ECARX incompleta: {data}")
        self.tokens = MyKoleosTokens(
            access_token=str(access),
            refresh_token=str(refresh),
            user_id=str(user_id),
            client_id=str(client_id),
            expires_at=(datetime.now(UTC) + timedelta(seconds=expires_in)).timestamp(),
        )
        return self.tokens

    async def login_with_code(self, auth_code: str, country_code: str) -> MyKoleosTokens:
        latam = await self.latam_login_code(auth_code, country_code)
        tsp_auth_code = recursive_find_value(latam, "tspAuthCode")
        latam_auth = recursive_find_value(latam, "authToken")
        latam_user = recursive_find_value(latam, "userid") or recursive_find_value(latam, "userId")
        if latam_auth:
            self.latam_auth_token = str(latam_auth)
        if latam_user:
            self.latam_user_id = str(latam_user)
        if not tsp_auth_code:
            raise MyKoleosAuthError(f"Resposta LATAM sem tspAuthCode: {latam}")
        return await self.ecarx_login_authcode(str(tsp_auth_code))

    async def refresh(self) -> MyKoleosTokens:
        if not self.refresh_token:
            raise MyKoleosAuthError("refreshToken ausente")
        data = await self._request(
            "PUT",
            "/auth/account/session/secure",
            body={"refreshToken": self.refresh_token},
            include_auth=True,
        )
        access = recursive_find_value(data, "accessToken")
        refresh = recursive_find_value(data, "refreshToken")
        client_id = recursive_find_value(data, "clientId") or self.client_id
        user_id = recursive_find_value(data, "userId") or recursive_find_value(data, "userid") or self.user_id
        expires_in = to_int(recursive_find_value(data, "expiresIn")) or 7200
        if not access or not refresh or not user_id or not client_id:
            raise MyKoleosAuthError(f"Resposta de refresh incompleta: {data}")
        self.tokens = MyKoleosTokens(
            access_token=str(access),
            refresh_token=str(refresh),
            user_id=str(user_id),
            client_id=str(client_id),
            expires_at=(datetime.now(UTC) + timedelta(seconds=expires_in)).timestamp(),
        )
        return self.tokens

    async def list_vehicles(self) -> dict[str, Any]:
        if not self.user_id:
            raise MyKoleosAuthError("userId ausente")
        return await self._request(
            "GET",
            "/device-platform/user/vehicle/secure",
            query=[("userId", self.user_id), ("needSharedCar", "1")],
        )

    async def discover_vehicle(self, fallback_vin: str | None = None, fallback_model_code: str | None = None) -> MyKoleosVehicle:
        data = await self.list_vehicles()
        vehicle_data = recursive_find_vehicle(data) or {}
        vin = str(vehicle_data.get("vin") or vehicle_data.get("VIN") or fallback_vin or "")
        model_code = str(
            vehicle_data.get("modelCode")
            or vehicle_data.get("model_code")
            or vehicle_data.get("model")
            or vehicle_data.get("vehicleSeries")
            or fallback_model_code
            or DEFAULT_MODEL_CODE
        )
        if not vin:
            raise MyKoleosAuthError("VIN não encontrado na lista de veículos")
        self.vehicle = MyKoleosVehicle(vin=vin, model_code=model_code)
        return self.vehicle

    def _latam_host_candidates(self, backend: str = "latam_auto") -> list[tuple[str, str]]:
        """Return LATAM host candidates for proxy testing.

        The APK exposes /api/1/proxy/... constants next to the REST host, but
        the production REST host can answer 404 for those paths. Keep the
        default as auto so we can test both the REST API host and the web
        host used by the redirect/app shell without changing YAML each time.
        """
        backend = (backend or "latam_auto").lower()
        rest_host = (self.latam_host or DEFAULT_LATAM_HOST).rstrip("/")
        web_host = DEFAULT_LATAM_WEB_HOST.rstrip("/")
        if backend in {"latam", "latam_auto", "auto"}:
            candidates: list[tuple[str, str]] = []
            for label, host in (("latam_rest", rest_host), ("latam_web", web_host)):
                if host and host not in [h for _, h in candidates]:
                    candidates.append((label, host))
            return candidates
        if backend in {"latam_rest", "rest"}:
            return [("latam_rest", rest_host)]
        if backend in {"latam_web", "web"}:
            return [("latam_web", web_host)]
        return [("latam_rest", rest_host)]

    def _latam_auth_attempts(
        self,
        *,
        method: str,
        query: list[tuple[str, str]],
        body: dict[str, Any] | None,
    ) -> list[tuple[str, list[tuple[str, str]], dict[str, Any] | None, dict[str, str]]]:
        """Build LATAM auth placement attempts.

        The decompiled LATAM app stores the login authToken as authKey and injects it
        as a token/authToken parameter for several routes. The first experimental
        remote implementation only tried Authorization, which can return "Invalid
        token" even when the token is valid but placed incorrectly for the route.
        """
        token = self.latam_auth_token or ""
        base_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Language": self.language,
            "User-Agent": "okhttp/4.12.0",
        }

        attempts: list[tuple[str, list[tuple[str, str]], dict[str, Any] | None, dict[str, str]]] = []

        def add(
            label: str,
            *,
            extra_query: list[tuple[str, str]] | None = None,
            extra_body: dict[str, Any] | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            q = list(query)
            if extra_query:
                q.extend(extra_query)
            b = dict(body or {}) if body is not None else None
            if extra_body:
                if b is None:
                    b = {}
                b.update(extra_body)
            h = dict(base_headers)
            if extra_headers:
                h.update(extra_headers)
            attempts.append((label, q, b, h))

        # Try both raw token and standard bearer token. The ECARX SDK uses raw
        # Authorization, but LATAM proxy endpoints can sit behind a different
        # gateway and may require Bearer or a custom token header.
        add("authorization_raw", extra_headers={"Authorization": token})
        add("authorization_bearer", extra_headers={"Authorization": f"Bearer {token}"})

        # Try common mobile/API header variants. These are safe to attempt because
        # only one placement is sent per request.
        for header_name in (
            "authKey",
            "AuthKey",
            "authToken",
            "AuthToken",
            "token",
            "X-Auth-Token",
            "X-Authorization",
            "X-Access-Token",
        ):
            add(f"header_{header_name}", extra_headers={header_name: token})

        # The LATAM helper also injects tokens as request parameters for app URLs.
        # Test all observed/plausible parameter names both in query and body.
        token_param_names = ("authToken", "token", "authKey", "accessToken")
        for name in token_param_names:
            add(f"query_{name}", extra_query=[(name, token)])
        if method.upper() != "GET":
            for name in token_param_names:
                add(f"body_{name}", extra_body={name: token})

        return attempts

    async def _latam_request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, Any] | None = None,
        backend: str = "latam_auto",
    ) -> Any:
        """Send a request to the My Koleos LATAM backend.

        This is used for the app's /api/1/proxy remote-command surface. Payloads,
        host and token placement are still experimental, so this method tries
        several LATAM auth placements and host candidates before failing.
        """
        if not self.latam_auth_token:
            raise MyKoleosAuthError(
                "LATAM authToken ausente. Gere um code= na URL de login e chame o serviço "
                "my_koleos.latam_login_code para habilitar comandos remotos nesta entrada."
            )

        verb = method.upper()
        base_query = list(query or [])
        last_auth_error: tuple[int, Any, str, str] | None = None
        route_errors: list[str] = []

        for host_label, host in self._latam_host_candidates(backend):
            for label, attempt_query, attempt_body, headers in self._latam_auth_attempts(
                method=verb, query=base_query, body=body
            ):
                query_string = encode_query(attempt_query)
                url = host.rstrip("/") + path + (f"?{query_string}" if query_string else "")
                body_text = json_compact(attempt_body) if attempt_body is not None else None
                try:
                    async with self.session.request(
                        verb,
                        url,
                        headers=headers,
                        data=body_text.encode("utf-8") if body_text is not None else None,
                        timeout=30,
                    ) as resp:
                        text = await resp.text()
                        try:
                            data = json.loads(text) if text else {}
                        except json.JSONDecodeError:
                            data = {"raw": text}
                        if resp.status in (401, 403):
                            last_auth_error = (resp.status, data, f"{host_label}/{label}", url.split("?")[0])
                            _LOGGER.debug(
                                "LATAM auth attempt %s/%s failed for %s %s: HTTP %s",
                                host_label,
                                label,
                                verb,
                                path,
                                resp.status,
                            )
                            continue
                        if resp.status in (404, 405):
                            # 404/405 is route/method/host, not token placement.
                            # Do not spam every auth placement on a path that is not there.
                            route_errors.append(f"{host_label} {verb} {path}: HTTP {resp.status}")
                            _LOGGER.debug(
                                "LATAM route attempt failed for %s %s on %s: HTTP %s",
                                verb,
                                path,
                                host_label,
                                resp.status,
                            )
                            break
                        if resp.status >= 400:
                            raise MyKoleosConnectionError(f"HTTP {resp.status}: {data}")
                        _LOGGER.info(
                            "LATAM remote command succeeded using host/auth mode %s/%s",
                            host_label,
                            label,
                        )
                        return data
                except MyKoleosError:
                    raise
                except (ClientError, TimeoutError, ClientResponseError) as exc:
                    raise MyKoleosConnectionError(str(exc)) from exc

        if last_auth_error is not None and not route_errors:
            status, data, label, _url = last_auth_error
            raise MyKoleosAuthError(
                f"HTTP {status}: {data}. O authToken LATAM está salvo, mas o gateway não aceitou "
                f"nenhuma posição conhecida de autenticação (última tentativa: {label}). "
                "Isto indica formato/payload do endpoint ou esquema de auth ainda não mapeado, não falta de login. "
                "Use my_koleos.debug_entries para confirmar a entrada e my_koleos.send_proxy_command para testar backend/payload."
            )

        if route_errors:
            detail = "; ".join(route_errors[-8:])
            auth_detail = ""
            if last_auth_error is not None:
                status, data, label, _url = last_auth_error
                auth_detail = f" Também houve auth em {label}: HTTP {status}: {data}."
            raise MyKoleosConnectionError(
                f"Endpoint proxy não encontrado neste host/método. Tentativas: {detail}.{auth_detail} "
                "Teste backend: latam_web/latam_rest e método GET/POST com my_koleos.send_proxy_command."
            )

        raise MyKoleosAuthError("Falha LATAM desconhecida; reautentique a integração")

    def _rce2_hvac_payload(self, *, start: bool, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the confirmed RCE_2 HVAC payload used by the My Koleos LATAM app."""
        payload = payload or {}
        if not self.user_id:
            raise MyKoleosAuthError("userId ECARX ausente")

        def _int_from_payload(*keys: str, default: int) -> int:
            for key in keys:
                value = payload.get(key)
                if value is None or value == "":
                    continue
                try:
                    return int(float(value))
                except (TypeError, ValueError) as exc:
                    raise MyKoleosError(f"Valor inválido para {key}: {value}") from exc
            return default

        now_ms = str(int(time.time() * 1000))
        body: dict[str, Any] = {
            "command": "start" if start else "stop",
            "timestamp": now_ms,
            "serviceId": "RCE_2",
            "creator": "tc",
            "userId": self.user_id,
            "operationScheduling": {
                "duration": 0,
                "interval": 0,
                "occurs": 1,
                "recurrentOperation": False,
            },
            "serviceParameters": [
                {"key": "rce.conditioner", "value": "1"},
            ],
        }
        if start:
            temperature = _int_from_payload("temperature", "temp", "target_temperature", default=DEFAULT_CLIMATE_TEMPERATURE)
            minutes = _int_from_payload("minutes", "duration_minutes", "duration", default=DEFAULT_CLIMATE_DURATION_MINUTES)
            if not 16 <= temperature <= 30:
                raise MyKoleosError("Temperatura da climatização deve estar entre 16 e 30 °C.")
            if not 1 <= minutes <= 30:
                raise MyKoleosError("Duração da climatização deve estar entre 1 e 30 minutos.")
            body["operationScheduling"]["duration"] = minutes * 6
            body["serviceParameters"] = [
                {"key": "rce.temp", "value": str(temperature)},
                {"key": "rce.conditioner", "value": "1"},
            ]
        return body

    def _remote_base_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.vin:
            payload["vin"] = self.vin
        # LATAM and ECARX user ids can differ. Include both names as a testing aid.
        if self.latam_user_id or self.user_id:
            payload["userId"] = self.latam_user_id or self.user_id
        return payload

    def _backend_candidates(self, backend: str) -> list[str]:
        """Return backend candidates for a remote command attempt."""
        backend = (backend or "auto").lower()
        if backend in {"auto", "remote_auto"}:
            # Try LATAM first because the decompiled paths live in the LATAM package,
            # then ECARX signed API in case /proxy is a TSP-side route.
            return ["latam_auto", "ecarx"]
        return [backend]

    def _route_candidates(
        self,
        command: str,
        endpoint: str,
        requested_verb: str,
        base_body: dict[str, Any],
        *,
        explicit_path: bool,
        explicit_method: bool,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Return path/method/body candidates for a named command.

        For explicit raw endpoint calls, do not add aliases: the user is testing
        exactly that URL. For named commands, allow known HCB replacements to be
        tested automatically after the legacy proxy path fails.
        """
        candidates: list[tuple[str, str, dict[str, Any]]] = []
        verb_candidates = [requested_verb]
        if not explicit_method and command in REMOTE_READ_COMMANDS and requested_verb == "POST":
            verb_candidates.append("GET")
        for verb in verb_candidates:
            candidates.append((endpoint, verb, dict(base_body)))

        if explicit_path:
            return candidates

        for alias in REMOTE_ROUTE_ALIASES.get(command, []):
            alias_path = str(alias.get("path") or "").strip()
            if not alias_path:
                continue
            alias_method = (str(alias.get("method") or requested_verb)).upper()
            alias_body = dict(self._remote_base_payload())
            alias_body.update(alias.get("payload") or {})
            # User-provided payload always wins over alias defaults.
            for key, value in base_body.items():
                if key not in alias_body or key not in {"vin", "userId"}:
                    alias_body[key] = value
            candidate = (alias_path, alias_method, alias_body)
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _is_route_error(self, exc: MyKoleosConnectionError) -> bool:
        text = str(exc)
        return (
            "Endpoint proxy não encontrado" in text
            or "HTTP 404" in text
            or "HTTP 405" in text
            or "Not Found" in text
        )

    async def send_proxy_command(
        self,
        command: str,
        *,
        payload: dict[str, Any] | None = None,
        method: str | None = None,
        path: str | None = None,
        query: list[tuple[str, str]] | None = None,
        backend: str = "auto",
        merge_defaults: bool = True,
    ) -> dict[str, Any]:
        """Send an experimental remote command.

        command may be one of REMOTE_PROXY_COMMANDS. path allows raw endpoint testing.
        backend='auto' tries LATAM REST/web hosts and then the signed ECARX API.
        """
        definition = REMOTE_PROXY_COMMANDS.get(command, {})

        # v0.3.0 / com_ac_final: confirmed physical HVAC flow. Do not use LATAM
        # proxy/HCB guesses for HVAC anymore; the app sends RCE_2 directly to ECARX.
        if path is None and command in {"hvac_start", "hvac_stop"}:
            if not self.vin:
                raise MyKoleosAuthError("VIN ausente")
            body = self._rce2_hvac_payload(start=command == "hvac_start", payload=payload)
            result = await self._request(
                "PUT",
                f"/remote-control/vehicle/telematics/{quote(self.vin, safe='')}",
                body=body,
                include_auth=True,
            )
            return {
                "backend": "ecarx",
                "path": "/remote-control/vehicle/telematics/{vin}",
                "method": "PUT",
                "payload_kind": "rce2_hvac_com_ac_final",
                "data": result,
            }

        # v0.2.6: res_state in the legacy LATAM /api/1/proxy surface returns 404
        # in production. The decompiled ECARX Retrofit interface has live read-only
        # status routes, and the integration already uses them for sensors. Treat
        # res_state as a safe ECARX state refresh first, before probing legacy proxy
        # paths. This does not send a physical vehicle command.
        if path is None and (command in {"res_state", "ecarx_state", "ecarx_status"}):
            if command == "ecarx_status":
                return await self.status(latest="local")
            if command == "ecarx_state":
                return await self.state()
            state_error: MyKoleosError | None = None
            try:
                state_data = await self.state()
                return {"backend": "ecarx", "path": "/remote-control/vehicle/status/state/{vin}", "data": state_data}
            except MyKoleosError as exc:
                state_error = exc
            try:
                status_data = await self.status(latest="local")
                return {"backend": "ecarx", "path": "/remote-control/vehicle/status/{vin}", "data": status_data}
            except MyKoleosError as exc:
                _LOGGER.debug("ECARX res_state status fallback failed after state error %s: %s", state_error, exc)
                # Continue into the legacy route probes below so the diagnostic output
                # still shows whether proxy/HCB remains unavailable.

        endpoint = path or definition.get("path")
        if not endpoint:
            raise MyKoleosError(f"Comando remoto desconhecido: {command}")
        requested_verb = (method or definition.get("method") or "POST").upper()
        body: dict[str, Any] = {}
        if merge_defaults:
            body.update(self._remote_base_payload())
            body.update(definition.get("payload") or {})
        if payload:
            body.update(payload)

        explicit_path = path is not None
        explicit_method = method is not None
        routes = self._route_candidates(command, endpoint, requested_verb, body, explicit_path=explicit_path, explicit_method=explicit_method)
        backends = self._backend_candidates(backend)

        route_errors: list[str] = []
        auth_errors: list[str] = []
        last_auth: MyKoleosAuthError | None = None
        last_route: MyKoleosConnectionError | None = None

        for candidate_path, verb, candidate_body in routes:
            for backend_choice in backends:
                try:
                    if backend_choice == "ecarx":
                        result = await self._request(
                            verb,
                            candidate_path,
                            query=query,
                            body=candidate_body if verb != "GET" else None,
                            include_auth=True,
                        )
                    else:
                        result = await self._latam_request(
                            verb,
                            candidate_path,
                            query=query,
                            body=candidate_body if verb != "GET" else None,
                            backend=backend_choice,
                        )
                    _LOGGER.info(
                        "My Koleos remote command %s succeeded on %s %s via %s",
                        command,
                        verb,
                        candidate_path,
                        backend_choice,
                    )
                    return result
                except MyKoleosAuthError as exc:
                    last_auth = exc
                    auth_errors.append(f"{backend_choice} {verb} {candidate_path}: {exc}")
                    continue
                except MyKoleosConnectionError as exc:
                    if self._is_route_error(exc):
                        last_route = exc
                        route_errors.append(f"{backend_choice} {verb} {candidate_path}: {exc}")
                        continue
                    raise

        details: list[str] = []
        if route_errors:
            details.append("rotas: " + " | ".join(route_errors[-8:]))
        if auth_errors:
            details.append("auth: " + " | ".join(auth_errors[-4:]))
        if details:
            raise MyKoleosConnectionError(
                "Nenhuma rota remota respondeu com sucesso. "
                + "\n".join(details)
                + "\nIsto confirma que a API proxy/HCB ainda precisa de captura real do app para path/método/payload. "
                "Para res_state, a v0.2.6 usa primeiro as rotas ECARX de status/state já validadas pelos sensores; use send_proxy_command apenas para mapear comandos físicos como HVAC."
            ) from (last_route or last_auth)
        if last_auth is not None:
            raise last_auth
        if last_route is not None:
            raise last_route
        raise MyKoleosError(f"Comando remoto não executado: {command}")

    async def update_session(self) -> dict[str, Any]:
        if not self.vin or not self.access_token:
            raise MyKoleosAuthError("VIN ou accessToken ausente")
        return await self._request(
            "POST",
            "/device-platform/user/session/update",
            query=[("vin", self.vin)],
            body={"language": "ko_KR", "vin": self.vin, "sessionToken": self.access_token},
        )

    async def status(self, latest: str = "local") -> dict[str, Any]:
        if not self.vin or not self.user_id:
            raise MyKoleosAuthError("VIN ou userId ausente")
        return await self._request(
            "GET",
            f"/remote-control/vehicle/status/{quote(self.vin, safe='')}",
            query=[("userId", self.user_id), ("latest", latest), ("target", "")],
        )

    async def state(self) -> dict[str, Any]:
        if not self.vin or not self.user_id:
            raise MyKoleosAuthError("VIN ou userId ausente")
        return await self._request(
            "GET",
            f"/remote-control/vehicle/status/state/{quote(self.vin, safe='')}",
            query=[("userId", self.user_id)],
        )

