"""대전 버스 데이터 코디네이터.

기본은 자동 갱신(polling)을 하지 않는다. 통합구성요소 로드 시 1회, 이후에는
새로고침 버튼(또는 homeassistant.update_entity 서비스)을 누를 때만 조회한다.
옵션에서 자동 조회를 켜면 지정한 요일/시간대에만 주기적으로 조회한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import slugify
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import commute
from .api import DaejeonBusApi, DaejeonBusAuthError, DaejeonBusError
from .const import (
    CONF_AUTO_END,
    CONF_AUTO_INTERVAL,
    CONF_AUTO_REFRESH,
    CONF_AUTO_START,
    CONF_AUTO_WEEKDAYS,
    CONF_LEAVE_MARGIN,
    CONF_ROUTE_CD,
    CONF_ROUTE_NO,
    CONF_STATION_NAME,
    CONF_STOP_SEQ,
    CONF_WALK_MINUTES,
    DEFAULT_AUTO_END,
    DEFAULT_AUTO_INTERVAL,
    DEFAULT_AUTO_START,
    DEFAULT_AUTO_WEEKDAYS,
    DEFAULT_BUS_METERS_PER_MINUTE,
    DEFAULT_LEAVE_MARGIN,
    DEFAULT_WALK_MINUTES,
    MIN_AUTO_INTERVAL,
    ROUTE_STOPS_MAX_AGE_HOURS,
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
from .schedule import in_window, parse_time
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


class DaejeonBusBaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """공통: API, 설정값, 기기 정보, 선택적 자동 조회."""

    config_entry: ConfigEntry

    # 엔티티 unique_id / entity_id / 기기 식별에 쓰는 값 (하위 클래스에서 지정)
    unique_key: str
    slug: str
    device_name: str
    device_model: str

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str) -> None:
        conf = {**entry.data, **entry.options}
        self.api = DaejeonBusApi(async_get_clientsession(hass), conf[CONF_API_KEY])
        self.last_success_time: datetime | None = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=name,
            # None = 주기 갱신 안 함. 새로고침 버튼(또는 선택한 자동 조회)으로만 갱신.
            update_interval=None,
        )

    @property
    def conf(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    # ---- 자동 조회 (옵션, 기본 꺼짐) ----

    @property
    def auto_refresh_enabled(self) -> bool:
        return bool(self.conf.get(CONF_AUTO_REFRESH, False))

    def in_auto_window(self, now: datetime) -> bool:
        conf = self.conf
        return in_window(
            now,
            parse_time(conf.get(CONF_AUTO_START), parse_time(DEFAULT_AUTO_START, time(7))),
            parse_time(conf.get(CONF_AUTO_END), parse_time(DEFAULT_AUTO_END, time(9))),
            # 키가 없을 때만 기본값 (빈 목록 = 어떤 요일도 아님)
            list(conf.get(CONF_AUTO_WEEKDAYS, DEFAULT_AUTO_WEEKDAYS)),
        )

    @callback
    def async_setup_auto_refresh(self) -> None:
        """자동 조회가 켜져 있으면 타이머를 등록한다 (항목 언로드 시 해제)."""
        if not self.auto_refresh_enabled:
            return
        try:
            interval = int(float(self.conf.get(CONF_AUTO_INTERVAL, DEFAULT_AUTO_INTERVAL)))
        except (TypeError, ValueError):
            interval = DEFAULT_AUTO_INTERVAL
        interval = max(interval, MIN_AUTO_INTERVAL)

        async def _tick(now: datetime) -> None:
            if self.in_auto_window(dt_util.as_local(now)):
                await self.async_refresh()

        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, _tick, timedelta(seconds=interval))
        )
        _LOGGER.debug("%s: 자동 조회 사용 (%s초 간격)", self.name, interval)


class DaejeonBusCoordinator(DaejeonBusBaseCoordinator):
    """정류소(arsId)의 버스 도착정보를 조회한다."""

    device_model = "정류소 버스도착정보"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        self.unique_key = self.slug = str(conf[CONF_STATION_ID])
        self.stop_names: dict[str, str] | None = None
        # 정류소정보 API로도 이름을 못 찾은 arsId (재조회 방지)
        self._unknown_stops: set[str] = set()
        self._station_api_ok = True
        super().__init__(hass, entry, f"{DOMAIN}_{conf[CONF_STATION_ID]}")

    @property
    def device_name(self) -> str:
        name = (
            self.conf.get(CONF_STATION_NAME)
            or (self.data or {}).get("stop_name")
            or f"정류소 {self.unique_key}"
        )
        return f"{name} ({self.unique_key})"

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


StationCoordinator = DaejeonBusCoordinator


class CommuteCoordinator(DaejeonBusBaseCoordinator):
    """출근 알리미: 노선의 모든 버스가 내 정류장에서 몇 정류장/몇 분 전인지."""

    device_model = "출근 알리미 (노선 추적)"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        self.route_cd = str(conf[CONF_ROUTE_CD])
        self.route_no = str(conf.get(CONF_ROUTE_NO) or self.route_cd)
        self.station_id = str(conf[CONF_STATION_ID])
        self.stop_seq = int(conf[CONF_STOP_SEQ])
        self.unique_key = f"commute_{self.route_cd}_{self.stop_seq}"
        self.slug = f"commute_{slugify(self.route_no)}_{self.station_id}"
        self._stops: list[commute.RouteStop] = []
        self._stops_fetched: datetime | None = None
        super().__init__(hass, entry, f"{DOMAIN}_{self.unique_key}")

    @property
    def my_stop(self) -> commute.RouteStop | None:
        return commute.stop_by_seq(self._stops, self.stop_seq)

    @property
    def device_name(self) -> str:
        stop = self.my_stop
        stop_name = stop.name if stop else self.station_id
        return f"{self.route_no}번 → {stop_name} 출근"

    def _minutes(self, key: str, default: float) -> float:
        try:
            return max(0.0, float(self.conf.get(key, default)))
        except (TypeError, ValueError):
            return default

    @property
    def walk_seconds(self) -> int:
        return int(self._minutes(CONF_WALK_MINUTES, DEFAULT_WALK_MINUTES) * 60)

    @property
    def leave_margin_seconds(self) -> int:
        return int(self._minutes(CONF_LEAVE_MARGIN, DEFAULT_LEAVE_MARGIN) * 60)

    async def _async_ensure_stops(self) -> None:
        """노선 정류소 목록은 하루에 한 번만 받는다."""
        now = dt_util.utcnow()
        if (
            self._stops
            and self._stops_fetched
            and now - self._stops_fetched < timedelta(hours=ROUTE_STOPS_MAX_AGE_HOURS)
        ):
            return
        stops = commute.parse_route_stops(await self.api.get_route_stops(self.route_cd))
        if not stops:
            raise DaejeonBusError(f"노선 {self.route_cd}의 정류소 목록이 비어 있습니다")
        self._stops = stops
        self._stops_fetched = now

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._async_ensure_stops()
            positions = await self.api.get_bus_positions(self.route_cd)
        except DaejeonBusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DaejeonBusError as err:
            raise UpdateFailed(str(err)) from err

        my_stop = self.my_stop
        if my_stop is None:
            raise UpdateFailed(
                f"노선 {self.route_no}에 {self.stop_seq}번째 정류소가 없습니다. 다시 설정하세요."
            )

        # 도착정보는 실제 도착예정시간 보정용. 실패해도 위치 기반 추정으로 계속한다.
        try:
            arrivals = await self.api.get_arrivals(self.station_id)
        except DaejeonBusError as err:
            _LOGGER.debug("도착정보 조회 실패, 추정값 사용: %s", err)
            arrivals = []

        buses = commute.approaching_buses(self._stops, my_stop, positions)
        speed = commute.apply_eta(
            buses, arrivals, self.route_cd, DEFAULT_BUS_METERS_PER_MINUTE
        )
        plan = commute.leave_plan(buses, self.walk_seconds)

        self.last_success_time = dt_util.now()
        return {
            "buses": buses,
            "plan": plan,
            "speed_m_per_min": round(speed),
            "my_stop": my_stop,
            "running": len(positions),
        }
