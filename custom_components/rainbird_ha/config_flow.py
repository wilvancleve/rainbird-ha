"""Config flow for rainbird_ha.

Onboarding drives the app's OIDC authorization-code + PKCE login from the user's
email/password, minting Home Assistant its own refresh-token lineage (independent
of the phone app).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEFAULT_MINUTES,
    CONF_DEVICE_UUID,
    CONF_REFRESH_TOKEN,
    CONF_SATELLITE_ID,
    CONF_SATELLITE_NAME,
    DEFAULT_MINUTES,
    DOMAIN,
)
from .client.iq4 import (
    IQ4AuthError,
    IQ4Client,
    IQ4Error,
    Satellite,
    login_with_password,
)

_LOGGER = logging.getLogger(__name__)


class RainbirdConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._refresh_token: str | None = None
        self._satellites: list[Satellite] = []
        self._client_id: str = ""
        self._client_secret: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # The OAuth client_id/secret are not shipped; the user captures their
            # own from the app (see tools/) and provides them here.
            self._client_id = user_input[CONF_CLIENT_ID].strip()
            self._client_secret = user_input[CONF_CLIENT_SECRET].strip()
            session = async_get_clientsession(self.hass)
            try:
                auth = await login_with_password(
                    session,
                    user_input[CONF_USERNAME].strip(),
                    user_input[CONF_PASSWORD],
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                )
                self._satellites = await IQ4Client(auth).get_satellites()
            except IQ4AuthError:
                errors["base"] = "invalid_auth"
            except IQ4Error:
                errors["base"] = "cannot_connect"
            else:
                if not self._satellites:
                    errors["base"] = "no_controllers"
                else:
                    self._refresh_token = auth.refresh_token
                    if len(self._satellites) == 1:
                        return await self._create(self._satellites[0])
                    return await self.async_step_select()

        fields: dict[Any, Any] = {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_CLIENT_ID): str,
            vol.Required(CONF_CLIENT_SECRET): str,
        }
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(fields), errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            sat = next(s for s in self._satellites
                       if s.id == int(user_input[CONF_SATELLITE_ID]))
            return await self._create(sat)
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema({
                vol.Required(CONF_SATELLITE_ID): vol.In(
                    {str(s.id): s.name for s in self._satellites}
                )
            }),
        )

    async def _create(self, sat: Satellite) -> ConfigFlowResult:
        await self.async_set_unique_id(str(sat.id))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=sat.name,
            data={
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_SATELLITE_ID: sat.id,
                CONF_SATELLITE_NAME: sat.name,
                CONF_DEVICE_UUID: sat.device_uuid,
                CONF_CLIENT_ID: self._client_id,
                CONF_CLIENT_SECRET: self._client_secret,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return RainbirdOptionsFlow()


class RainbirdOptionsFlow(OptionsFlow):
    """Options: default run duration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get(CONF_DEFAULT_MINUTES, DEFAULT_MINUTES)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_DEFAULT_MINUTES, default=current):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=240)),
            }),
        )
