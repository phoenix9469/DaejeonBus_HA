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
from typing import Any


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


def apply_eta(
    buses: list[dict[str, Any]],
    arrivals: list[dict[str, Any]],
    route_cd: str,
    default_meters_per_minute: float,
) -> float:
    """버스별 도착예정(초)을 채운다. 반환값은 사용한 속도(m/분).

    도착정보 API에 같은 차량번호가 있으면 그 값을 쓰고(estimated=False),
    없으면 남은 거리 / 속도로 추정한다. 속도는 실제 도착정보가 있는 버스로 보정한다.
    """
    eta_by_plate: dict[str, int] = {}
    for item in arrivals:
        if _str(item.get("ROUTE_CD")) != _str(route_cd):
            continue
        if _str(item.get("MSG_TP")) == "07":  # 차고지 운행대기
            continue
        sec = _int(item.get("EXTIME_SEC"))
        plate = _str(item.get("CAR_REG_NO"))
        if plate and sec is not None:
            eta_by_plate[plate] = sec

    samples = []
    for bus in buses:
        sec = eta_by_plate.get(bus["plate"])
        bus["eta_seconds"] = sec
        bus["estimated"] = sec is None
        if sec and bus["meters_away"] > 0:
            samples.append(bus["meters_away"] / (sec / 60))

    speed = sum(samples) / len(samples) if samples else default_meters_per_minute
    for bus in buses:
        if bus["eta_seconds"] is None:
            bus["eta_seconds"] = int(bus["meters_away"] / speed * 60) if speed > 0 else None
    return speed


def leave_plan(
    buses: list[dict[str, Any]], walk_seconds: int
) -> dict[str, Any] | None:
    """걸어가서 탈 수 있는 첫 버스와 출발까지 남은 시간(초)."""
    for index, bus in enumerate(buses):
        eta = bus.get("eta_seconds")
        if eta is None or eta < walk_seconds:
            continue
        return {
            "index": index,
            "bus": bus,
            "leave_in_seconds": eta - walk_seconds,
        }
    return None
