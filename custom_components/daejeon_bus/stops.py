"""정류소 번호(arsId) -> 정류소 이름 캐시.

이름은 파일(/config/.storage/daejeon_bus_stop_names)에 저장해 두고,
파일에 없는 정류소는 그 버스 노선의 경유 정류장 목록(getStaionByRoute)을 받아 파일에 추가한다.
노선으로 조회가 받는 노선 경유 정류소 목록의 이름도 같은 파일에 넣는다.
모든 항목(정류소/노선으로 조회)이 하나의 캐시를 공유한다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import DaejeonBusApi, DaejeonBusError
from .commute import parse_route_stops
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_stop_names"
STORAGE_VERSION = 1
SAVE_DELAY = 10  # 초. 여러 번 바뀌어도 한 번에 저장
DATA_KEY = "stop_names"  # hass.data[DOMAIN][DATA_KEY]


class StopNameCache:
    """arsId -> 정류소 이름. 파일 캐시 + 노선 경유 정류장 API."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._names: dict[str, str] = {}
        self._loaded = False
        self._lock = asyncio.Lock()
        # 이번 실행 중 API로도 이름을 못 찾은 arsId (재조회 방지, 파일에는 저장 안 함)
        self._unknown: set[str] = set()
        # 이번 실행 중 정류장 목록을 이미 받은 노선
        self._fetched_routes: set[str] = set()
        self._api_ok = True

    async def async_load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            data = await self._store.async_load() or {}
            self._names = {
                str(k): str(v) for k, v in (data.get("stops") or {}).items() if v
            }
            self._loaded = True
            _LOGGER.debug("정류소 이름 캐시 %d개를 읽었습니다", len(self._names))

    def get(self, ars_id: Any) -> str | None:
        ars_id = str(ars_id or "").strip()
        return self._names.get(ars_id) if ars_id else None

    def __len__(self) -> int:
        return len(self._names)

    def _schedule_save(self) -> None:
        self._store.async_delay_save(lambda: {"stops": dict(sorted(self._names.items()))}, SAVE_DELAY)

    def async_add(self, names: dict[str, str]) -> None:
        """이름을 캐시에 추가 (바뀐 게 있으면 파일 저장 예약)."""
        changed = False
        for ars_id, name in names.items():
            ars_id, name = str(ars_id).strip(), str(name).strip()
            if ars_id and name and self._names.get(ars_id) != name:
                self._names[ars_id] = name
                changed = True
        if changed:
            self._schedule_save()

    async def async_resolve(self, api: DaejeonBusApi, stop_routes: dict[str, str]) -> None:
        """캐시에 없는 정류장 이름을 노선 경유 정류장 API로 채운다.

        stop_routes: {정류장 arsId: 그 정류장을 지나는 노선 ID(ROUTE_CD, 8자리)}
        도착정보의 LAST_STOP_ID는 그 버스 노선 위의 정류장이므로, 노선 정류장 목록
        (busRouteInfo/getStaionByRoute)을 한 번 받으면 그 노선 정류장 이름을 모두 얻는다.
        노선마다 실행 중 한 번만 조회한다.
        """
        await self.async_load()
        if not self._api_ok:
            return
        missing = {
            a: r
            for a, r in stop_routes.items()
            if a and a not in self._names and a not in self._unknown
        }
        routes = sorted({r for r in missing.values() if r and r not in self._fetched_routes})
        if not routes:
            # 이미 받은 노선에도 없는 정류장은 더 찾지 않는다
            self._unknown.update(missing)
            return

        results = await asyncio.gather(
            *(api.get_route_stops(r) for r in routes), return_exceptions=True
        )
        found: dict[str, str] = {}
        failures = 0
        for route_cd, result in zip(routes, results):
            if isinstance(result, Exception):
                failures += 1
                _LOGGER.debug("노선 %s 정류장 목록 조회 실패: %s", route_cd, result)
                continue
            self._fetched_routes.add(route_cd)
            for stop in parse_route_stops(result):
                if stop.ars_id and stop.name:
                    found.setdefault(stop.ars_id, stop.name)
        self.async_add(found)
        self._unknown.update(a for a in missing if a not in self._names)

        if failures == len(routes):
            # 서비스키에 노선정보 서비스 권한이 없는 경우 등: 재시작 전까지 조회 중단
            self._api_ok = False
            _LOGGER.warning(
                "노선 정류장 API(busRouteInfo/getStaionByRoute)로 정류장 이름을 받을 수 없어 "
                "정류장 번호로 표시합니다. 공공데이터포털에서 대전광역시 버스노선정보 조회 "
                "서비스 활용신청 여부를 확인하세요. 마지막 오류: %s",
                next((r for r in reversed(results) if isinstance(r, DaejeonBusError)), None),
            )

    async def async_clear(self) -> int:
        """캐시 파일을 지우고 메모리도 비운다. 지운 정류장 수를 돌려준다."""
        await self.async_load()
        count = len(self._names)
        await self._store.async_remove()
        self._names = {}
        self._unknown = set()
        self._fetched_routes = set()
        self._api_ok = True
        _LOGGER.info("정류장 이름 캐시 %d개를 삭제했습니다", count)
        return count


def get_stop_cache(hass: HomeAssistant) -> StopNameCache:
    """모든 항목이 공유하는 캐시."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if DATA_KEY not in domain_data:
        domain_data[DATA_KEY] = StopNameCache(hass)
    return domain_data[DATA_KEY]
