"""대전광역시 버스정보(BIS) 공공데이터포털 API 클라이언트."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.util import dt as dt_util
import xmltodict
from yarl import URL

from .const import ARRIVE_URL, BUS_POS_URL, ROUTE_STOPS_URL, STATION_URLS

_LOGGER = logging.getLogger(__name__)

# msgHeader.headerCd: 0 = 정상, 4 = 결과 없음
_HEADER_OK = {"0", "00"}
_HEADER_NO_DATA = {"4", "04"}


class DaejeonBusError(Exception):
    """API 호출 실패."""


class DaejeonBusAuthError(DaejeonBusError):
    """서비스키 오류."""


def _encode_key(api_key: str) -> str:
    """공공데이터포털 서비스키를 URL에 넣을 수 있게 인코딩한다.

    인코딩된 키(%2B 등 포함)와 디코딩된 키(+, /, = 포함) 모두 허용한다.
    """
    api_key = api_key.strip()
    if "%" in api_key:
        return api_key
    return quote(api_key, safe="")


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def parse_response(text: str) -> list[dict[str, Any]]:
    """ServiceResult XML을 파싱해 itemList를 반환한다."""
    try:
        data = xmltodict.parse(text)
    except Exception as err:  # noqa: BLE001
        raise DaejeonBusError(f"응답 파싱 실패: {text[:200]}") from err

    # 공공데이터포털 게이트웨이 오류 (서비스키 미등록, 트래픽 초과 등)
    if "OpenAPI_ServiceResponse" in data:
        header = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader") or {}
        reason = header.get("returnAuthMsg") or header.get("errMsg") or "unknown"
        code = str(header.get("returnReasonCode") or "")
        if "KEY" in reason or code in {"20", "30", "31", "32"}:
            raise DaejeonBusAuthError(reason)
        raise DaejeonBusError(reason)

    result = data.get("ServiceResult") or data.get("response")
    if not isinstance(result, dict):
        raise DaejeonBusError(f"알 수 없는 응답 형식: {text[:200]}")

    header = result.get("msgHeader") or {}
    code = str(header.get("headerCd", "0")).strip()
    if code in _HEADER_NO_DATA:
        return []
    if code not in _HEADER_OK:
        msg = header.get("headerMsg") or code
        raise DaejeonBusError(f"API 오류({code}): {msg}")

    body = result.get("msgBody") or {}
    return _as_list(body.get("itemList"))


class DaejeonBusApi:
    """대전 버스 API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._key = _encode_key(api_key)
        self._station_url: str | None = None
        # 오늘 API(서비스)별 실제 호출 수
        self._calls_date = dt_util.now().date()
        self._calls: dict[str, int] = {}

    @property
    def calls_today(self) -> dict[str, int]:
        if dt_util.now().date() != self._calls_date:
            return {}
        return dict(self._calls)

    def _count(self, base: str) -> None:
        today = dt_util.now().date()
        if today != self._calls_date:
            self._calls_date, self._calls = today, {}
        service = base.rstrip("/").split("/")[-2]  # .../<service>/<operation>
        self._calls[service] = self._calls.get(service, 0) + 1

    async def _get(self, base: str, **params: str) -> list[dict[str, Any]]:
        query = "&".join(
            [f"serviceKey={self._key}"]
            + [f"{k}={quote(str(v).strip(), safe='')}" for k, v in params.items()]
        )
        # 서비스키가 이중 인코딩되지 않도록 encoded=True
        url = URL(f"{base}?{query}", encoded=True)
        self._count(base)
        try:
            async with asyncio.timeout(15):
                async with self._session.get(url) as resp:
                    text = await resp.text()
                    if resp.status in (401, 403):
                        raise DaejeonBusAuthError(f"HTTP {resp.status}: {text[:200]}")
                    if resp.status != 200:
                        raise DaejeonBusError(f"HTTP {resp.status}: {text[:200]}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DaejeonBusError(f"통신 오류: {err}") from err
        return parse_response(text)

    async def get_arrivals(self, ars_id: str) -> list[dict[str, Any]]:
        """정류소(arsId)의 버스 도착정보."""
        return await self._get(ARRIVE_URL, arsId=ars_id)


    async def get_bus_positions(self, route_cd: str) -> list[dict[str, Any]]:
        """노선(busRouteId)에서 운행 중인 버스 위치."""
        return await self._get(BUS_POS_URL, busRouteId=route_cd)

    async def get_route_stops(self, route_cd: str) -> list[dict[str, Any]]:
        """노선(busRouteId)의 경유 정류소 목록."""
        return await self._get(ROUTE_STOPS_URL, busRouteId=route_cd)

    async def get_station_name(self, ars_id: str) -> str | None:
        """정류소(arsId)의 이름(BUSSTOP_NM). 정류소정보 조회 서비스 사용.

        사용 가능한 엔드포인트를 찾으면 기억해 두고, 어느 곳도 응답하지 않으면
        DaejeonBusError를 발생시킨다.
        """
        urls = [self._station_url] if self._station_url else list(STATION_URLS)
        last_err: DaejeonBusError | None = None
        for url in urls:
            try:
                items = await self._get(url, arsId=ars_id)
            except DaejeonBusError as err:
                last_err = err
                continue
            self._station_url = url
            for item in items:
                name = str(item.get("BUSSTOP_NM") or "").strip()
                if name:
                    return name
            return None
        raise last_err or DaejeonBusError("정류소정보 조회 실패")
