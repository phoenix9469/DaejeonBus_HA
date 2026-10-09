"""대전 버스 센서."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    API_NAMES,
    CONF_ENTRY_TYPE,
    DEV_DAILY_LIMIT,
    CONF_INCLUDE_BUSES,
    ENTRY_TYPE_COMMUTE,
    CONF_STATION_ID,
    DOMAIN,
    LAST_CAT_NAMES,
    MSG_TP_NAMES,
    ROUTE_TP_NAMES,
    STATUS_ARRIVED,
    STATUS_ENTERING,
    STATUS_SOON,
    STATUS_WAITING,
)
from .coordinator import (
    CommuteCoordinator,
    DaejeonBusBaseCoordinator,
    DaejeonBusCoordinator,
    arrival_seconds,
    bus_status,
    format_seconds,
    msg_type,
    parse_targets,
    sort_key,
    to_int,
)
from .entity import DaejeonBusEntity

NO_INFO = "도착정보 없음"


def _route_unique_id(station_id: str, route_no: str) -> str:
    return f"{DOMAIN}_{station_id}_route_{route_no}"


def arrival_text(coordinator: DaejeonBusCoordinator, item: dict[str, Any]) -> str | None:
    """상태로 보여줄 문구.

    도착 / 진입중 / 운행대기, 또는 '곧 도착 (1정류장 전)', '5분 7초 (4정류장 전)'.
    """
    status = bus_status(item, coordinator.soon_seconds)
    if status in (STATUS_ARRIVED, STATUS_ENTERING, STATUS_WAITING):
        return status
    text = status if status == STATUS_SOON else format_seconds(arrival_seconds(item))
    stops = to_int(item.get("STATUS_POS"))
    if text and stops:
        return f"{text} ({stops}정류장 전)"
    return text


def bus_info(coordinator: DaejeonBusCoordinator, item: dict[str, Any]) -> dict[str, Any]:
    """버스 1대의 도착정보를 사용자용 속성으로 변환."""
    status = bus_status(item, coordinator.soon_seconds)
    tp = msg_type(item)
    last_cat = str(item.get("LAST_CAT") or "").strip()
    info: dict[str, Any] = {
        "운행 상태": status,
        "메시지 유형": MSG_TP_NAMES.get(tp, tp or None),
        "첫/막차": LAST_CAT_NAMES.get(last_cat, last_cat or None),
        "차량번호": item.get("CAR_REG_NO"),
    }
    if status == STATUS_WAITING:
        # 운행대기(차고지 대기) 버스는 도착시간/위치 값이 의미 없다.
        info.update(
            {
                "도착예정시간": None,
                "도착예정(분)": None,
                "도착예정(초)": None,
                "잔여 정류장 수": None,
                "최근 통과 정류소": None,
                "최근 통과 정류소 ID": None,
            }
        )
    else:
        sec = arrival_seconds(item)
        last_stop_id = str(item.get("LAST_STOP_ID") or "").strip() or None
        info.update(
            {
                "도착예정시간": format_seconds(sec),
                "도착예정(분)": to_int(item.get("EXTIME_MIN")),
                "도착예정(초)": sec,
                "잔여 정류장 수": to_int(item.get("STATUS_POS")),
                "최근 통과 정류소": coordinator.stop_name(last_stop_id) or last_stop_id,
                "최근 통과 정류소 ID": last_stop_id,
            }
        )
    info["정보 제공 시각"] = item.get("INFO_OFFER_TM")
    return info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COMMUTE:
        _setup_commute(hass.data[DOMAIN][entry.entry_id], async_add_entities)
        return

    coordinator: DaejeonBusCoordinator = hass.data[DOMAIN][entry.entry_id]
    station_id = coordinator.conf[CONF_STATION_ID]
    targets = parse_targets(coordinator.conf.get(CONF_INCLUDE_BUSES))

    entities: list[SensorEntity] = [
        DaejeonBusStationSensor(coordinator),
        DaejeonBusLastUpdateSensor(coordinator),
        DaejeonBusApiUsageSensor(coordinator),
    ]

    # 노선 센서: 대상 버스 목록이 있으면 그 노선만, 없으면 이전에 만든 센서 + 현재 도착정보
    route_nos: list[str] = list(targets)
    prefix = f"{DOMAIN}_{station_id}_route_"
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain != "sensor" or not reg_entry.unique_id.startswith(prefix):
            continue
        route_no = reg_entry.unique_id[len(prefix):]
        if not targets:
            route_nos.append(route_no)
        elif route_no not in targets:
            # 대상 버스 목록에서 빠진 노선 센서는 정리
            ent_reg.async_remove(reg_entry.entity_id)
    if not targets:
        route_nos.extend((coordinator.data or {}).get("routes", {}))

    added: set[str] = set()

    def _new_route_sensors(route_nos: list[str]) -> list[SensorEntity]:
        new = []
        for route_no in route_nos:
            if route_no in added:
                continue
            added.add(route_no)
            new.append(DaejeonBusRouteSensor(coordinator, route_no))
        return new

    entities.extend(_new_route_sensors(route_nos))
    async_add_entities(entities)

    if targets:
        return

    # 새로고침 후 새로 나타난 노선은 센서를 추가한다.
    @callback
    def _async_add_new_routes() -> None:
        routes = (coordinator.data or {}).get("routes", {})
        if new := _new_route_sensors(list(routes)):
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_routes))


class DaejeonBusStationSensor(DaejeonBusEntity, SensorEntity):
    """정류소 요약: 도착예정 버스 수 + 전체 목록."""

    _attr_icon = "mdi:bus-stop"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: DaejeonBusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._station_id}_station"
        self._attr_name = "도착예정 버스"
        self.entity_id = f"sensor.{DOMAIN}_{slugify(self._station_id)}"

    @property
    def native_value(self) -> int:
        items = (self.coordinator.data or {}).get("items", [])
        return sum(1 for i in items if bus_status(i) != STATUS_WAITING)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        firsts = sorted(
            (items[0] for items in data.get("routes", {}).values()), key=sort_key
        )
        buses = [
            {
                "노선": str(first.get("ROUTE_NO") or "").strip(),
                "행선지": first.get("DESTINATION"),
                "노선유형": ROUTE_TP_NAMES.get(
                    str(first.get("ROUTE_TP") or "").strip()
                ),
                "도착예정": arrival_text(self.coordinator, first),
                **bus_info(self.coordinator, first),
            }
            for first in firsts
        ]
        return {
            "정류소 ID(arsId)": self._station_id,
            "정류소 이름": data.get("stop_name"),
            "버스 목록": buses,
        }


class DaejeonBusLastUpdateSensor(DaejeonBusEntity, SensorEntity):
    """마지막 조회 시각."""

    _attr_icon = "mdi:update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("sensor", "last_update")
        self._attr_name = "마지막 조회"

    @property
    def available(self) -> bool:
        return self.coordinator.last_success_time is not None

    @property
    def native_value(self):
        return self.coordinator.last_success_time


class DaejeonBusApiUsageSensor(DaejeonBusEntity, SensorEntity):
    """자동 조회 설정 기준 하루 예상 API 호출 수 (+ 오늘 실제 호출 수)."""

    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "회/일"

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("sensor", "api_usage")
        self._attr_name = "자동 조회 예상 API 호출"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int:
        return self.coordinator.auto_call_estimate()["total_per_day"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        est = self.coordinator.auto_call_estimate()
        api_key = self.coordinator.conf.get(CONF_API_KEY)
        # 같은 서비스키를 쓰는 모든 항목 합계 (한도는 키+서비스 단위)
        key_total: dict[str, int] = {}
        for other in self.hass.data.get(DOMAIN, {}).values():
            if (
                isinstance(other, DaejeonBusBaseCoordinator)
                and other.conf.get(CONF_API_KEY) == api_key
            ):
                for api, n in other.auto_call_estimate()["per_day"].items():
                    key_total[api] = key_total.get(api, 0) + n
        name = lambda api: API_NAMES.get(api, api)  # noqa: E731
        return {
            "자동 조회": "켜짐" if est["enabled"] else "꺼짐",
            "조회 간격(초)": est["interval"],
            "하루 자동 조회 횟수": est["refreshes_per_day"],
            "1회 조회당 호출": {name(a): n for a, n in self.coordinator.api_calls_per_refresh.items()},
            "API별 하루 예상": {name(a): n for a, n in est["per_day"].items()},
            "주간 예상 합계": est["total_per_week"],
            "개발계정 한도 대비(%)": est["busiest_percent"],
            "개발계정 일일 한도(서비스별)": DEV_DAILY_LIMIT,
            "같은 키 전체 하루 예상": {name(a): n for a, n in key_total.items()},
            "오늘 실제 호출": {name(a): n for a, n in self.coordinator.api.calls_today.items()},
        }


class DaejeonBusRouteSensor(DaejeonBusEntity, SensorEntity):
    """노선별 도착정보. 상태 = 가장 먼저 도착할 버스의 도착예정시간."""

    _attr_icon = "mdi:bus"

    def __init__(self, coordinator: DaejeonBusCoordinator, route_no: str) -> None:
        super().__init__(coordinator)
        self._route_no = route_no
        self._attr_unique_id = _route_unique_id(self._station_id, route_no)
        self._attr_name = f"{route_no}번"
        self.entity_id = (
            f"sensor.{DOMAIN}_{slugify(self._station_id)}_{slugify(route_no)}"
        )

    @property
    def _items(self) -> list[dict[str, Any]]:
        return (self.coordinator.data or {}).get("routes", {}).get(self._route_no, [])

    @property
    def native_value(self) -> str:
        items = self._items
        if not items:
            return NO_INFO
        return arrival_text(self.coordinator, items[0]) or NO_INFO

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._items
        attrs: dict[str, Any] = {"노선번호": self._route_no}
        if not items:
            return attrs
        first = items[0]
        attrs["노선 ID"] = first.get("ROUTE_CD")
        attrs["행선지"] = first.get("DESTINATION")
        route_tp = str(first.get("ROUTE_TP") or "").strip()
        attrs["노선유형"] = ROUTE_TP_NAMES.get(route_tp, route_tp or None)
        attrs.update(bus_info(self.coordinator, first))
        if len(items) > 1:
            attrs["다음 버스"] = [bus_info(self.coordinator, i) for i in items[1:]]
        return attrs


# ---------------------------------------------------------------------------
# 노선으로 조회
# ---------------------------------------------------------------------------



def _minutes(seconds: int | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def commute_bus_info(index: int, bus: dict[str, Any]) -> dict[str, Any]:
    """버스 1대 정보. 도착예정시간은 지금 오는(첫 번째) 버스에만 있다."""
    info = {
        "순번": index + 1,
        "차량번호": bus["plate"],
        "남은 정류장": bus["stops_away"],
        "남은 거리(m)": bus["meters_away"],
        "현재 정류장": bus["current_stop"],
        "현재 정류장 ID": bus["current_stop_id"],
    }
    if bus.get("eta_seconds") is not None:
        info["도착예정시간"] = format_seconds(bus["eta_seconds"])
        info["도착예정(초)"] = bus["eta_seconds"]
        info["도착예정(분)"] = _minutes(bus["eta_seconds"])
    return info


def _setup_commute(
    coordinator: CommuteCoordinator, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            CommuteStopsSensor(coordinator, 0),
            CommuteMinutesSensor(coordinator),
            CommuteStopsSensor(coordinator, 1),
            CommuteSummarySensor(coordinator),
            DaejeonBusLastUpdateSensor(coordinator),
            DaejeonBusApiUsageSensor(coordinator),
        ]
    )


class CommuteEntity(DaejeonBusEntity):
    coordinator: CommuteCoordinator

    @property
    def _buses(self) -> list[dict[str, Any]]:
        return (self.coordinator.data or {}).get("buses", [])


_ORDINAL = ("첫 번째", "두 번째")
_ORDINAL_KEY = ("first", "second")


class CommuteStopsSensor(CommuteEntity, SensorEntity):
    """n번째로 오는 버스가 몇 정류장 전인지."""

    _attr_icon = "mdi:bus-marker"
    _attr_native_unit_of_measurement = "정류장"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CommuteCoordinator, index: int) -> None:
        super().__init__(coordinator)
        self._index = index
        self._set_ids("sensor", f"{_ORDINAL_KEY[index]}_stops")
        self._attr_name = f"{_ORDINAL[index]} 버스 남은 정류장"

    @property
    def native_value(self) -> int | None:
        buses = self._buses
        return buses[self._index]["stops_away"] if len(buses) > self._index else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        buses = self._buses
        if len(buses) <= self._index:
            return None
        return commute_bus_info(self._index, buses[self._index])


class CommuteMinutesSensor(CommuteEntity, SensorEntity):
    """지금 오는(첫 번째) 버스의 도착예정 ('4분 48초'). 도착정보 API 값만 사용.

    자동화용 숫자는 속성 '도착예정(초)', '도착예정(분)'에 있다.
    """

    _attr_icon = "mdi:bus-clock"

    def __init__(self, coordinator: CommuteCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("sensor", "first_minutes")
        self._attr_name = "첫 번째 버스 도착예정"

    @property
    def native_value(self) -> str | None:
        buses = self._buses
        return format_seconds(buses[0].get("eta_seconds")) if buses else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        buses = self._buses
        return commute_bus_info(0, buses[0]) if buses else None


class CommuteSummarySensor(CommuteEntity, SensorEntity):
    """오고 있는 버스 수 + 전체 목록 (대시보드용)."""

    _attr_icon = "mdi:bus-multiple"
    _attr_native_unit_of_measurement = "대"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CommuteCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("sensor", None)
        self._attr_name = "오는 버스"

    @property
    def native_value(self) -> int:
        return len(self._buses)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        my_stop = data.get("my_stop")
        return {
            "노선번호": self.coordinator.route_no,
            "노선 ID": self.coordinator.route_cd,
            "내 정류장": my_stop.name if my_stop else None,
            "내 정류장 ID(arsId)": self.coordinator.station_id,
            "내 정류장 순번": self.coordinator.stop_seq,
            "운행 중인 버스 수": data.get("running"),
            "버스 목록": [commute_bus_info(i, b) for i, b in enumerate(self._buses)],
        }
