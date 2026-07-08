"""Constants for the My Koleos LATAM integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "my_koleos"
NAME = "My Koleos LATAM"

PLATFORMS = ["sensor", "binary_sensor", "device_tracker", "button", "switch"]

MIN_SCAN_INTERVAL_SECONDS = 15
DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)  # Backward compatibility with v0.1.0/v0.1.1.
DEFAULT_IDLE_SCAN_INTERVAL = timedelta(seconds=60)
DEFAULT_ACTIVE_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_ADAPTIVE_POLLING = True
DEFAULT_UPDATE_SESSION_ON_POLL = True

# Remote commands are experimental. Keep disabled by default.
DEFAULT_ENABLE_REMOTE_COMMANDS = False
DEFAULT_ALLOW_SENSITIVE_REMOTE_COMMANDS = False
DEFAULT_REMOTE_COMMAND_COOLDOWN_SECONDS = 20
DEFAULT_CLIMATE_TEMPERATURE = 22
DEFAULT_CLIMATE_DURATION_MINUTES = 10

CONF_ENABLE_REMOTE_COMMANDS = "enable_remote_commands"
CONF_ALLOW_SENSITIVE_REMOTE_COMMANDS = "allow_sensitive_remote_commands"
CONF_REMOTE_COMMAND_COOLDOWN = "remote_command_cooldown"
CONF_LATAM_AUTH_TOKEN = "latam_auth_token"
CONF_LATAM_USER_ID = "latam_user_id"
CONF_INSTANCE_ID = "instance_id"

DEFAULT_APP_ID = "renault_app"
DEFAULT_APP_SECRET = "16070e0ad7c24beba3c8da97eed65b45"
DEFAULT_OPERATOR = "renault"
DEFAULT_ENV = "production"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_DEVICE_TYPE = "mobile"
DEFAULT_DEVICE_IDENTIFIER = "0000000000000000"
DEFAULT_HOST = "https://api.ecloudus.com"
DEFAULT_LATAM_HOST = "https://latam-rsm-rest-api.renaultkoream.com"
DEFAULT_LATAM_WEB_HOST = "https://my-rk-latam.renaultkoream.com"
DEFAULT_COUNTRY_CODE = "BR"
DEFAULT_MODEL_CODE = "R745"

CONF_AUTH_CODE = "auth_code"
CONF_COUNTRY_CODE = "country_code"
CONF_APP_SECRET = "app_secret"
CONF_DEVICE_IDENTIFIER = "device_identifier"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IDLE_SCAN_INTERVAL = "idle_scan_interval"
CONF_ACTIVE_SCAN_INTERVAL = "active_scan_interval"
CONF_ADAPTIVE_POLLING = "adaptive_polling"
CONF_UPDATE_SESSION_ON_POLL = "update_session_on_poll"
CONF_VIN = "vin"
CONF_MODEL_CODE = "model_code"
CONF_USER_ID = "user_id"
CONF_CLIENT_ID = "client_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

GIGYA_AUTH_BASE = "https://gigya-prod-us1.idconnect-am.renaultgroup.com/oidc/op/v1.0/4_yTFqPSsGxVyRXPZUM7t1Iw/authorize"
GIGYA_CLIENT_ID = "CVXws_Di4gM8nGxpxZO5PUoX"
GIGYA_REDIRECT_URI = "https://my-rk-latam.renaultkoream.com/page/webLink/latamRedirect"
GIGYA_CODE_CHALLENGE = "oKowxfuNEaj81UZkl1qv2c-xIxT_XPb6-eD55_3WpRg"
GIGYA_STATE = "T196SkVBX3NtRn5aYVdJSUYxTTAzNS5JSDlJTEhiZDVfTzhPZE95bDZTQUZFU3puSlg"

