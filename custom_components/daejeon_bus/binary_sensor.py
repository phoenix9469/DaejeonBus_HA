"""대전 버스 바이너리 센서 (노선으로 조회: 지금 나가야 하는지)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COMMUTE
from .coordinator import CommuteCoordinator
from .entity import DaejeonBusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COMMUTE:
        return
    async_add_entities([CommuteLeaveNowBinarySensor(hass.data[DOMAIN][entry.entry_id])])


class CommuteLeaveNowBinarySensor(DaejeonBusEntity, BinarySensorEntity):
    """출발까지 남은 시간이 '출발 알림 여유' 이하이면 on. 자동화 트리거용."""

    coordinator: CommuteCoordinator
    _attr_icon = "mdi:run-fast"

    def __init__(self, coordinator: CommuteCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("binary_sensor", "leave_now")
        self._attr_name = "지금 출발"

    @property
    def is_on(self) -> bool:
        plan = (self.coordinator.data or {}).get("plan")
        return bool(plan) and plan["leave_in_seconds"] <= self.coordinator.leave_margin_seconds

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = (self.coordinator.data or {}).get("plan")
        if not plan:
            return None
        bus = plan["bus"]
        return {
            "차량번호": bus["plate"],
            "남은 정류장": bus["stops_away"],
            "출발까지(초)": plan["leave_in_seconds"],
        }
