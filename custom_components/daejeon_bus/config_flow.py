"""대전 버스 설정 흐름."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import commute
from .api import DaejeonBusApi, DaejeonBusAuthError, DaejeonBusError
from .coordinator import CommuteCoordinator, StationCoordinator
from .schedule import estimate_auto_calls, format_estimate
from .const import (
    CONF_AUTO_END,
    CONF_AUTO_INTERVAL,
    CONF_AUTO_REFRESH,
    CONF_AUTO_START,
    CONF_AUTO_WEEKDAYS,
    CONF_ENTRY_TYPE,
    CONF_INCLUDE_BUSES,
    CONF_ROUTE_CD,
    CONF_ROUTE_NO,
    CONF_SOON_MINUTES,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_STOP_SEQ,
    DEFAULT_AUTO_END,
    DEFAULT_AUTO_INTERVAL,
    DEFAULT_AUTO_START,
    DEFAULT_AUTO_WEEKDAYS,
    DEFAULT_SOON_MINUTES,
    DOMAIN,
    ENTRY_TYPE_COMMUTE,
    ENTRY_TYPE_STATION,
    MIN_AUTO_INTERVAL,
    WEEKDAYS,
)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
    return {k: v for k, v in data.items() if v != ""}


def _minutes_selector(max_value: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=max_value,
            step=1,
            unit_of_measurement="분",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _auto_refresh_schema(conf: dict[str, Any]) -> dict:
    """자동 조회 옵션 (두 항목 유형 공통)."""
    return {
        vol.Optional(
            CONF_AUTO_REFRESH, default=conf.get(CONF_AUTO_REFRESH, False)
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_AUTO_START, default=conf.get(CONF_AUTO_START, DEFAULT_AUTO_START)
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_AUTO_END, default=conf.get(CONF_AUTO_END, DEFAULT_AUTO_END)
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_AUTO_WEEKDAYS,
            default=conf.get(CONF_AUTO_WEEKDAYS, DEFAULT_AUTO_WEEKDAYS),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=WEEKDAYS,
                multiple=True,
                translation_key="weekday",
            )
        ),
        vol.Optional(
            CONF_AUTO_INTERVAL, default=conf.get(CONF_AUTO_INTERVAL, DEFAULT_AUTO_INTERVAL)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_AUTO_INTERVAL,
                max=600,
                step=5,
                unit_of_measurement="초",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }


class DaejeonBusConfigFlow(ConfigFlow, domain=DOMAIN):
    """정류장 도착정보 / 노선으로 조회."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._routes: dict[str, dict[str, str]] = {}
        self._stops: list[commute.RouteStop] = []
        self._candidates: list[commute.RouteStop] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[ENTRY_TYPE_STATION, ENTRY_TYPE_COMMUTE]
        )

    # ---- 정류소 도착정보 ----

    async def async_step_station(
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
                return self.async_create_entry(
                    title=title, data={CONF_ENTRY_TYPE: ENTRY_TYPE_STATION, **data}
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="station",
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

    # ---- 노선으로 조회 ----

    def _api(self) -> DaejeonBusApi:
        return DaejeonBusApi(async_get_clientsession(self.hass), self._data[CONF_API_KEY])

    async def async_step_commute(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """1단계: API 키 + 내 정류장."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COMMUTE, **_clean(user_input)}
            try:
                items = await self._api().get_arrivals(self._data[CONF_STATION_ID])
            except DaejeonBusAuthError:
                errors["base"] = "invalid_auth"
            except DaejeonBusError:
                errors["base"] = "cannot_connect"
            else:
                # 이 정류장을 지나는 노선 (도착정보 기준)
                self._routes = {}
                for item in items:
                    route_cd = str(item.get("ROUTE_CD") or "").strip()
                    if route_cd and route_cd not in self._routes:
                        self._routes[route_cd] = {
                            "no": str(item.get("ROUTE_NO") or route_cd).strip(),
                            "dest": str(item.get("DESTINATION") or "").strip(),
                        }
                return await self.async_step_commute_route()

        user_input = user_input or {}
        return self.async_show_form(
            step_id="commute",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=user_input.get(CONF_API_KEY, "")): str,
                    vol.Required(CONF_STATION_ID, default=user_input.get(CONF_STATION_ID, "")): str,
                }
            ),
            errors=errors,
        )

    async def async_step_commute_route(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """2단계: 노선 선택 (목록에 없으면 노선 ID 8자리 직접 입력)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            route = str(user_input[CONF_ROUTE_CD]).strip()
            # 노선번호를 입력한 경우 노선 ID로 변환
            route_cd = next(
                (cd for cd, r in self._routes.items() if r["no"] == route), route
            )
            try:
                self._stops = commute.parse_route_stops(
                    await self._api().get_route_stops(route_cd)
                )
            except DaejeonBusError:
                errors["base"] = "cannot_connect"
            else:
                self._candidates = commute.find_stops(self._stops, self._data[CONF_STATION_ID])
                if not self._stops:
                    errors[CONF_ROUTE_CD] = "route_not_found"
                elif not self._candidates:
                    errors[CONF_ROUTE_CD] = "stop_not_on_route"
                else:
                    self._data[CONF_ROUTE_CD] = route_cd
                    self._data[CONF_ROUTE_NO] = self._routes.get(route_cd, {}).get("no", route_cd)
                    if len(self._candidates) == 1:
                        self._data[CONF_STOP_SEQ] = self._candidates[0].seq
                        return await self._async_create_commute_entry()
                    return await self.async_step_commute_direction()

        options = [
            selector.SelectOptionDict(
                value=cd, label=f"{r['no']}번 ({r['dest']} 방면)" if r["dest"] else f"{r['no']}번"
            )
            for cd, r in sorted(self._routes.items(), key=lambda kv: kv[1]["no"])
        ]
        return self.async_show_form(
            step_id="commute_route",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROUTE_CD): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_commute_direction(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """3단계(필요할 때만): 노선이 내 정류장을 두 번 지나면 방향 선택."""
        if user_input is not None:
            self._data[CONF_STOP_SEQ] = int(user_input[CONF_STOP_SEQ])
            return await self._async_create_commute_entry()

        options = []
        for stop in self._candidates:
            nxt = commute.next_stop(self._stops, stop)
            label = f"{stop.seq}번째 정류장" + (f" (다음: {nxt.name})" if nxt else " (종점)")
            options.append(selector.SelectOptionDict(value=str(stop.seq), label=label))
        return self.async_show_form(
            step_id="commute_direction",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_SEQ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def _async_create_commute_entry(self) -> ConfigFlowResult:
        await self.async_set_unique_id(
            f"commute_{self._data[CONF_ROUTE_CD]}_{self._data[CONF_STOP_SEQ]}"
        )
        self._abort_if_unique_id_configured()
        stop = commute.stop_by_seq(self._stops, self._data[CONF_STOP_SEQ])
        stop_name = stop.name if stop else self._data[CONF_STATION_ID]
        return self.async_create_entry(
            title=f"{self._data[CONF_ROUTE_NO]}번 → {stop_name}",
            data=self._data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DaejeonBusOptionsFlow()


class DaejeonBusOptionsFlow(OptionsFlow):
    """항목 유형별 옵션 + 자동 조회."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}

    def _estimate(self, conf: dict[str, Any]) -> dict[str, Any]:
        cls = (
            CommuteCoordinator
            if self.config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COMMUTE
            else StationCoordinator
        )
        return estimate_auto_calls(conf, cls.api_calls_per_refresh, cls.api_calls_per_day_extra)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
            if self.config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COMMUTE:
                # 화면에서 칸을 비우면 키 자체가 빠진다. 그대로 두면 처음 설정값(data)이
                # 다시 쓰이므로 빈 값으로 명시해 '전체 노선' / 'API 이름 사용'으로 돌아가게 한다.
                for key in (CONF_STATION_NAME, CONF_INCLUDE_BUSES):
                    data.setdefault(key, "")
            self._pending = data
            if data.get(CONF_AUTO_REFRESH):
                # 자동 조회를 켜면 저장 전에 예상 API 호출 수를 보여준다
                return await self.async_step_auto_confirm()
            return self.async_create_entry(title="", data=data)

        conf = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}
        schema: dict = {vol.Required(CONF_API_KEY, default=conf.get(CONF_API_KEY, "")): str}
        if conf.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COMMUTE:
            schema.update(
                {
                    # default 대신 suggested_value: 칸을 비우면 키가 빠지고, 위에서 ""로 저장된다
                    vol.Optional(
                        CONF_STATION_NAME,
                        description={"suggested_value": conf.get(CONF_STATION_NAME, "")},
                    ): str,
                    vol.Optional(
                        CONF_INCLUDE_BUSES,
                        description={"suggested_value": conf.get(CONF_INCLUDE_BUSES, "")},
                    ): str,
                    vol.Optional(
                        CONF_SOON_MINUTES,
                        default=conf.get(CONF_SOON_MINUTES, DEFAULT_SOON_MINUTES),
                    ): _minutes_selector(30),
                }
            )
        schema.update(_auto_refresh_schema(conf))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders={"estimate": format_estimate(self._estimate(conf))},
        )

    async def async_step_auto_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """자동 조회 예상 API 호출 수 확인 후 저장."""
        if user_input is not None:
            return self.async_create_entry(title="", data=self._pending)
        conf = {**self.config_entry.data, **self.config_entry.options, **self._pending}
        return self.async_show_form(
            step_id="auto_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"estimate": format_estimate(self._estimate(conf))},
        )
