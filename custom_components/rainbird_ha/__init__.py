"""The Rain Bird (self-hosted IQ4) integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CARD_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_UUID,
    CONF_REFRESH_TOKEN,
    CONF_SATELLITE_ID,
    DOMAIN,
    VERSION,
)
from .coordinator import RainbirdCoordinator
from .client.iq4 import IQ4Auth, IQ4AuthError, IQ4Error
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH,
]


def _read_token(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.exists() else None


def _write_token(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data))


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and auto-load it (once per HA start)."""
    if hass.data.get(f"{DOMAIN}_card"):
        return
    hass.data[f"{DOMAIN}_card"] = True
    card = Path(__file__).parent / "frontend" / "rainbird_ha_card.js"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card), False)]
        )
        # Cache-bust on upgrade so browsers pick up the new card automatically.
        frontend.add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    except Exception as err:  # noqa: BLE001 - card is optional, never block setup
        _LOGGER.warning("Could not auto-register the Rain Bird card: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up rainbird_ha from a config entry."""
    satellite_id = entry.data[CONF_SATELLITE_ID]
    token_path = Path(hass.config.path(f".storage/{DOMAIN}_{satellite_id}_token.json"))

    # Build auth off the event loop: load the persisted (rotated) token if present,
    # else seed from the entry. Persist rotations back to .storage via the executor.
    # client_id/secret are user-supplied at setup (captured from the app).
    auth = IQ4Auth(
        async_get_clientsession(hass),
        entry.data[CONF_REFRESH_TOKEN],
        client_id=entry.data[CONF_CLIENT_ID],
        client_secret=entry.data[CONF_CLIENT_SECRET],
    )
    if (loaded := await hass.async_add_executor_job(_read_token, token_path)):
        auth.apply_tokens(loaded)

    async def _save(data: dict[str, Any]) -> None:
        await hass.async_add_executor_job(_write_token, token_path, data)

    auth.on_token_update = _save

    coordinator = RainbirdCoordinator(
        hass, entry,
        satellite_id=satellite_id,
        device_uuid=entry.data[CONF_DEVICE_UUID],
        auth=auth,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except IQ4AuthError as err:
        # Bad/expired refresh token -> trigger reauth rather than silent failure.
        raise ConfigEntryNotReady(f"Authentication failed: {err}") from err
    except IQ4Error as err:
        raise ConfigEntryNotReady(f"Could not reach IQ4 service: {err}") from err

    await coordinator.async_start_stream()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)
    await _async_register_card(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: RainbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop_stream()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:  # last controller unloaded
            async_unload_services(hass)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options change."""
    await hass.config_entries.async_reload(entry.entry_id)
