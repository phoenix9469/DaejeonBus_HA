"""대전 버스 데이터 코디네이터.

자동 갱신(polling)은 하지 않는다. 통합구성요소 로드 시 1회, 이후에는
새로고침 버튼(또는 homeassistant.update_entity 서비스)을 누를 때만 조회한다.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DaejeonBusApi, DaejeonBusAuthError, DaejeonBusError
from .const import CONF_INCLUDE_BUSES, CONF_STATION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


def parse_targets(value: str | None) -> list[str]:
    """쉼표로 구분된 대상 버스 목록."""
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def arrival_seconds(item: dict[str, Any]) -> int | None:
    """도착 예정 시간(초). EXTIME_SEC는 전체 초, EXTIME_MIN은 올림한 분이다."""
    sec = to_int(item.get("EXTIME_SEC"))
    if sec is not None:
        return sec
    minutes = to_int(item.get("EXTIME_MIN"))
    return minutes * 60 if minutes is not None else None


def format_seconds(sec: int | None) -> str | None:
    """초를 'N분 M초' 형식으로."""
    if sec is None:
        return None
    if sec < 60:
        return f"{sec}초"
    minutes, seconds = divmod(sec, 60)
    return f"{minutes}분 {seconds}초" if seconds else f"{minutes}분"


def group_arrivals(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """도착정보를 노선번호(ROUTE_NO)별로 묶고 도착 예정 순으로 정렬한다."""
    routes: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        route_no = str(item.get("ROUTE_NO") or item.get("ROUTE_CD") or "").strip()
        if not route_no:
            continue
        routes.setdefault(route_no, []).append(item)
    for buses in routes.values():
        buses.sort(key=lambda i: s if (s := arrival_seconds(i)) is not None else 1 << 30)
    return routes


class DaejeonBusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """정류소(arsId)의 버스 도착정보를 조회한다."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        self.api = DaejeonBusApi(async_get_clientsession(hass), conf[CONF_API_KEY])
        self.last_success_time = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{conf[CONF_STATION_ID]}",
            # None = 자동 갱신 안 함. 새로고침 버튼으로만 갱신.
            update_interval=None,
        )

    @property
    def conf(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def _async_update_data(self) -> dict[str, Any]:
        conf = self.conf
        try:
            items = await self.api.get_arrivals(conf[CONF_STATION_ID])
        except DaejeonBusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DaejeonBusError as err:
            raise UpdateFailed(str(err)) from err

        targets = parse_targets(conf.get(CONF_INCLUDE_BUSES))
        if targets:
            items = [
                i
                for i in items
                if str(i.get("ROUTE_NO", "")).strip() in targets
                or str(i.get("ROUTE_CD", "")).strip() in targets
            ]

        stop_name = next(
            (str(i["STOP_NAME"]).strip() for i in items if i.get("STOP_NAME")), None
        )
        self.last_success_time = dt_util.now()
        return {
            "items": items,
            "routes": group_arrivals(items),
            "stop_name": stop_name,
        }
