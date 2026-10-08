"""대전 버스 센서."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_INCLUDE_BUSES, CONF_STATION_ID, DOMAIN
from .coordinator import (
    DaejeonBusCoordinator,
    arrival_seconds,
    format_seconds,
    parse_targets,
    to_int,
)
from .entity import DaejeonBusEntity

NO_INFO = "도착정보 없음"


def _route_unique_id(station_id: str, route_no: str) -> str:
    return f"{DOMAIN}_{station_id}_route_{route_no}"


def bus_info(item: dict[str, Any]) -> dict[str, Any]:
    """버스 1대의 도착정보를 사용자용 속성으로 변환."""
    sec = arrival_seconds(item)
    return {
        "도착예정시간": format_seconds(sec),
        "도착예정(분)": to_int(item.get("EXTIME_MIN")),
        "도착예정(초)": sec,
        "잔여 정류장 수": to_int(item.get("STATUS_POS")),
        "최근 통과 정류소": (str(item.get("LAST_STOP_ID") or "").strip() or None),
        "차량번호": item.get("CAR_REG_NO"),
        "정보 제공 시각": item.get("INFO_OFFER_TM"),
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DaejeonBusCoordinator = hass.data[DOMAIN][entry.entry_id]
    station_id = coordinator.conf[CONF_STATION_ID]
    targets = parse_targets(coordinator.conf.get(CONF_INCLUDE_BUSES))

    entities: list[SensorEntity] = [
        DaejeonBusStationSensor(coordinator),
        DaejeonBusLastUpdateSensor(coordinator),
    ]

    # 노선 센서: 대상 버스 목록 > 이전에 만든 센서 > 현재 도착정보 순으로 구성
    route_nos: list[str] = list(targets)
    if not targets:
        prefix = f"{DOMAIN}_{station_id}_route_"
        ent_reg = er.async_get(hass)
        for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if reg_entry.domain == "sensor" and reg_entry.unique_id.startswith(prefix):
                route_nos.append(reg_entry.unique_id[len(prefix):])
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
        return len((self.coordinator.data or {}).get("items", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        buses = []
        for route_no, items in data.get("routes", {}).items():
            first = items[0]
            buses.append(
                {
                    "노선": route_no,
                    "행선지": first.get("DESTINATION"),
                    **bus_info(first),
                }
            )
        buses.sort(
            key=lambda b: b["도착예정(초)"] if b["도착예정(초)"] is not None else 1 << 30
        )
        return {
            "정류소 ID(arsId)": self._station_id,
            "정류소 이름": data.get("stop_name"),
            "버스 목록": buses,
        }


class DaejeonBusLastUpdateSensor(DaejeonBusEntity, SensorEntity):
    """마지막 조회 시각."""

    _attr_icon = "mdi:update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DaejeonBusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._station_id}_last_update"
        self._attr_name = "마지막 조회"
        self.entity_id = f"sensor.{DOMAIN}_{slugify(self._station_id)}_last_update"

    @property
    def available(self) -> bool:
        return self.coordinator.last_success_time is not None

    @property
    def native_value(self):
        return self.coordinator.last_success_time


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
        return format_seconds(arrival_seconds(items[0])) or NO_INFO

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._items
        attrs: dict[str, Any] = {"노선번호": self._route_no}
        if not items:
            return attrs
        first = items[0]
        attrs["노선 ID"] = first.get("ROUTE_CD")
        attrs["행선지"] = first.get("DESTINATION")
        attrs.update(bus_info(first))
        if len(items) > 1:
            attrs["다음 버스"] = [bus_info(i) for i in items[1:]]
        return attrs
