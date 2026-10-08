"""대전 버스 설정 흐름."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DaejeonBusApi, DaejeonBusAuthError, DaejeonBusError
from .const import CONF_INCLUDE_BUSES, CONF_STATION_ID, CONF_STATION_NAME, DOMAIN


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
    return {k: v for k, v in data.items() if v != ""}


class DaejeonBusConfigFlow(ConfigFlow, domain=DOMAIN):
    """정류소(arsId) 하나당 하나의 항목."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(data[CONF_STATION_ID])
            self._abort_if_unique_id_configured()

            api = DaejeonBusApi(async_get_clientsession(self.hass), data[CONF_API_KEY])
            stop_name = None
            try:
                items = await api.get_arrivals(data[CONF_STATION_ID])
                stop_name = next((i["STOP_NAME"] for i in items if i.get("STOP_NAME")), None)
            except DaejeonBusAuthError:
                errors["base"] = "invalid_auth"
            except DaejeonBusError:
                errors["base"] = "cannot_connect"

            if not errors:
                name = data.get(CONF_STATION_NAME) or stop_name
                title = f"{name} ({data[CONF_STATION_ID]})" if name else f"정류소 {data[CONF_STATION_ID]}"
                return self.async_create_entry(title=title, data=data)

        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=user_input.get(CONF_API_KEY, "")): str,
                    vol.Required(CONF_STATION_ID, default=user_input.get(CONF_STATION_ID, "")): str,
                    vol.Optional(CONF_STATION_NAME, default=user_input.get(CONF_STATION_NAME, "")): str,
                    vol.Optional(CONF_INCLUDE_BUSES, default=user_input.get(CONF_INCLUDE_BUSES, "")): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DaejeonBusOptionsFlow()


class DaejeonBusOptionsFlow(OptionsFlow):
    """API 키, 정류소 이름, 대상 버스 변경."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
            return self.async_create_entry(title="", data=data)

        conf = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=conf.get(CONF_API_KEY, "")): str,
                    vol.Optional(CONF_STATION_NAME, default=conf.get(CONF_STATION_NAME, "")): str,
                    vol.Optional(CONF_INCLUDE_BUSES, default=conf.get(CONF_INCLUDE_BUSES, "")): str,
                }
            ),
        )
