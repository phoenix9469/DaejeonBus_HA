"""대전 버스 데이터 코디네이터.

자동 갱신(polling)은 하지 않는다. 통합구성요소 로드 시 1회, 이후에는
새로고침 버튼(또는 homeassistant.update_entity 서비스)을 누를 때만 조회한다.
"""
from __future__ import annotations

import asyncio
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
from .const import (
    CONF_INCLUDE_BUSES,
    CONF_SOON_MINUTES,
    CONF_STATION_ID,
    CONF_STOPS_CSV,
    DEFAULT_SOON_MINUTES,
    DOMAIN,
    MSG_TP_ARRIVED,
    MSG_TP_ENTERING,
    MSG_TP_WAITING,
    STATUS_ARRIVED,
    STATUS_ENTERING,
    STATUS_RUNNING,
    STATUS_SOON,
    STATUS_WAITING,
)
from .stops import load_stop_names

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


def msg_type(item: dict[str, Any]) -> str:
    return str(item.get("MSG_TP") or "").strip()


def bus_status(item: dict[str, Any], soon_seconds: int = 0) -> str:
    """운행 상태: 도착 / 진입중 / 곧 도착 / 운행대기 / 운행중.

    soon_seconds 이하로 남은 운행중 버스는 '곧 도착'이다 (0이면 사용 안 함).
    """
    tp = msg_type(item)
    if tp == MSG_TP_ARRIVED:
        return STATUS_ARRIVED
    if tp == MSG_TP_ENTERING:
        return STATUS_ENTERING
    if tp == MSG_TP_WAITING:
        return STATUS_WAITING
    sec = arrival_seconds(item)
    if soon_seconds > 0 and sec is not None and sec <= soon_seconds:
        return STATUS_SOON
    return STATUS_RUNNING


def sort_key(item: dict[str, Any]) -> tuple[int, int]:
    """운행대기 버스는 맨 뒤, 나머지는 도착 예정 순."""
    sec = arrival_seconds(item)
    return (msg_type(item) == MSG_TP_WAITING, sec if sec is not None else 1 << 30)


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
        buses.sort(key=sort_key)
    return routes


class DaejeonBusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """정류소(arsId)의 버스 도착정보를 조회한다."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        self.api = DaejeonBusApi(async_get_clientsession(hass), conf[CONF_API_KEY])
        self.last_success_time = None
        self.stop_names: dict[str, str] | None = None
        # 정류소정보 API로도 이름을 못 찾은 arsId (재조회 방지)
        self._unknown_stops: set[str] = set()
        self._station_api_ok = True
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

    @property
    def soon_seconds(self) -> int:
        """'곧 도착'으로 표시할 기준(초)."""
        try:
            minutes = float(self.conf.get(CONF_SOON_MINUTES, DEFAULT_SOON_MINUTES))
        except (TypeError, ValueError):
            minutes = DEFAULT_SOON_MINUTES
        return max(0, int(minutes * 60))

    def stop_name(self, ars_id: Any) -> str | None:
        ars_id = str(ars_id or "").strip()
        if not ars_id:
            return None
        return (self.stop_names or {}).get(ars_id)

    async def _async_update_data(self) -> dict[str, Any]:
        conf = self.conf
        if self.stop_names is None:
            self.stop_names = await self.hass.async_add_executor_job(
                load_stop_names, conf.get(CONF_STOPS_CSV)
            )
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

        await self._async_resolve_stop_names(items)

        stop_name = next(
            (str(i["STOP_NAME"]).strip() for i in items if i.get("STOP_NAME")), None
        )
        self.last_success_time = dt_util.now()
        return {
            "items": items,
            "routes": group_arrivals(items),
            "stop_name": stop_name,
        }

    async def _async_resolve_stop_names(self, items: list[dict[str, Any]]) -> None:
        """변환표에 없는 최근 통과 정류소는 정류소정보 API로 이름을 조회한다."""
        if not self._station_api_ok:
            return
        names = self.stop_names if self.stop_names is not None else {}
        missing = {
            ars_id
            for i in items
            if (ars_id := str(i.get("LAST_STOP_ID") or "").strip())
            and ars_id not in names
            and ars_id not in self._unknown_stops
        }
        if not missing:
            return

        missing_list = sorted(missing)
        results = await asyncio.gather(
            *(self.api.get_station_name(a) for a in missing_list),
            return_exceptions=True,
        )
        failures = 0
        for ars_id, result in zip(missing_list, results):
            if isinstance(result, str):
                names[ars_id] = result
            else:
                self._unknown_stops.add(ars_id)
                if isinstance(result, Exception):
                    failures += 1
                    _LOGGER.debug("정류소 %s 이름 조회 실패: %s", ars_id, result)
        if failures == len(missing_list):
            # 서비스키에 정류소정보 서비스 권한이 없는 경우 등: 이번 세션은 더 시도하지 않음
            self._station_api_ok = False
            _LOGGER.info(
                "정류소정보 API로 정류소 이름을 조회할 수 없어 정류소 번호로 표시합니다. "
                "공공데이터포털에서 '대전광역시_정류소정보조회' 서비스 활용신청 여부를 "
                "확인하거나, 설정에서 정류소 CSV 파일을 지정하세요."
            )
