"""Constants for the rainbird_ha integration."""

DOMAIN = "rainbird_ha"
# Keep in sync with manifest.json "version" — used to cache-bust the frontend card.
VERSION = "1.2.3"

# URL the integration serves its bundled Lovelace card at.
CARD_URL = f"/{DOMAIN}/rainbird_ha_card.js"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_SATELLITE_ID = "satellite_id"
CONF_SATELLITE_NAME = "satellite_name"
CONF_DEVICE_UUID = "device_uuid"
CONF_DEFAULT_MINUTES = "default_minutes"
# OAuth client credentials — user-supplied at setup (captured from the app with
# tools/); not shipped with this project.
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"

DEFAULT_MINUTES = 10
# REST poll interval; the AppSync stream pushes near-instant updates in between.
SCAN_INTERVAL_SECONDS = 300
