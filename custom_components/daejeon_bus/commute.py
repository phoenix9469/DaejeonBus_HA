"""노선으로 조회 계산 (Home Assistant와 무관한 순수 함수).

- 노선 경유 정류소 목록(getStaionByRoute): 정류소 순번(BUSSTOP_SEQ)과 기점부터 누적거리(TOTAL_DIST)
- 노선 버스 위치(getBusPosByRtid): 버스별 기점부터 누적거리(TOTAL_DIST), 차량번호(PLATE_NO)
- 내 정류장 도착정보(getArrInfoByUid): 차량번호(CAR_REG_NO)별 도착예정시간(EXTIME_SEC)

누적거리는 왕복 전체 구간 기준이라 상행/하행이 자연스럽게 구분된다.
버스 누적거리 < 내 정류장 누적거리 이면 아직 오지 않은 버스다.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any, Callable


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class RouteStop:
    seq: int
    ars_id: str
    name: str
    dist: int


def parse_route_stops(items: list[dict[str, Any]]) -> list[RouteStop]:
    """경유 정류소 목록을 순번 순으로."""
    stops = []
    for item in items:
        seq = _int(item.get("BUSSTOP_SEQ"))
        dist = _int(item.get("TOTAL_DIST"))
        if seq is None or dist is None:
            continue
        stops.append(
            RouteStop(
                seq=seq,
                ars_id=_str(item.get("BUS_STOP_ID")),
                name=_str(item.get("BUSSTOP_NM")),
                dist=dist,
            )
        )
    stops.sort(key=lambda s: s.seq)
    return stops


def find_stops(stops: list[RouteStop], ars_id: str) -> list[RouteStop]:
    """노선에서 arsId에 해당하는 정류소 (순환 노선이면 여러 개일 수 있음)."""
    ars_id = _str(ars_id)
    return [s for s in stops if s.ars_id == ars_id]


def stop_by_seq(stops: list[RouteStop], seq: int) -> RouteStop | None:
    return next((s for s in stops if s.seq == seq), None)


def next_stop(stops: list[RouteStop], stop: RouteStop) -> RouteStop | None:
    """방향 구분용: 다음 정류소."""
    return next((s for s in stops if s.seq > stop.seq), None)


def locate(stops: list[RouteStop], dist: int) -> RouteStop:
    """누적거리 dist 위치의 버스가 마지막으로 지난(또는 서 있는) 정류소."""
    dists = [s.dist for s in stops]
    idx = bisect_right(dists, dist) - 1
    return stops[max(idx, 0)]


def approaching_buses(
    stops: list[RouteStop], my_stop: RouteStop, positions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """내 정류장으로 오고 있는 버스 목록 (가까운 순)."""
    buses = []
    for pos in positions:
        dist = _int(pos.get("TOTAL_DIST"))
        if dist is None or dist > my_stop.dist:
            continue  # 위치 불명 또는 이미 지나감
        current = locate(stops, dist)
        buses.append(
            {
                "plate": _str(pos.get("PLATE_NO") or pos.get("CAR_REG_NO")),
                "stops_away": max(my_stop.seq - current.seq, 0),
                "meters_away": my_stop.dist - dist,
                "current_stop": current.name,
                "current_stop_id": current.ars_id,
                "current_seq": current.seq,
            }
        )
    buses.sort(key=lambda b: b["meters_away"])
    return buses


def first_bus_eta(
    buses: list[dict[str, Any]], arrivals: list[dict[str, Any]], route_cd: str
) -> int | None:
    """지금 오는(첫 번째) 버스의 도착예정(초). 도착정보 API 값만 쓰고 추정하지 않는다.

    같은 차량번호가 있으면 그 값, 없으면(두 API 갱신 시점 차이) 이 노선의 가장 빠른 도착정보.
    결과는 buses[0]["eta_seconds"]에도 넣는다. 나머지 버스는 정류장 수만 보여준다.
    """
    for bus in buses:
        bus["eta_seconds"] = None
    if not buses:
        return None

    etas: list[tuple[int, str]] = []
    for item in arrivals:
        if _str(item.get("ROUTE_CD")) != _str(route_cd):
            continue
        if _str(item.get("MSG_TP")) == "07":  # 차고지 운행대기
            continue
        sec = _int(item.get("EXTIME_SEC"))
        if sec is not None:
            etas.append((sec, _str(item.get("CAR_REG_NO"))))
    if not etas:
        return None

    first = buses[0]
    eta = next((sec for sec, plate in etas if plate and plate == first["plate"]), None)
    if eta is None:
        eta = min(sec for sec, _ in etas)
    first["eta_seconds"] = eta
    return eta


def buses_from_arrivals(
    arrivals: list[dict[str, Any]],
    route_cd: str,
    stop_name: Callable[[str], str | None],
) -> list[dict[str, Any]]:
    """버스 위치 API를 못 쓸 때 대체: 도착정보 API로 이 노선 버스 목록을 만든다.

    도착정보에는 버스까지 남은 거리가 없으므로 meters_away 는 None.
    남은 정류장(STATUS_POS)과 도착예정(EXTIME_SEC)은 실제 값이다.
    """
    buses = []
    for item in arrivals:
        if _str(item.get("ROUTE_CD")) != _str(route_cd):
            continue
        if _str(item.get("MSG_TP")) == "07":  # 차고지 운행대기
            continue
        stops_away = _int(item.get("STATUS_POS"))
        if stops_away is None:
            continue
        last_stop = _str(item.get("LAST_STOP_ID"))
        buses.append(
            {
                "plate": _str(item.get("CAR_REG_NO")),
                "stops_away": stops_away,
                "meters_away": None,
                "current_stop": stop_name(last_stop) or last_stop or None,
                "current_stop_id": last_stop or None,
                "current_seq": None,
                "eta_seconds": _int(item.get("EXTIME_SEC")),
            }
        )
    buses.sort(key=lambda b: (b["stops_away"], b["eta_seconds"] or 0))
    return buses
