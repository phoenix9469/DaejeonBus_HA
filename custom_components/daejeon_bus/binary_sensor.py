"""대전 버스 바이너리 센서: 공공데이터포털 일일 요청 한도 초과."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import API_NAMES, DOMAIN
from .coordinator import DaejeonBusBaseCoordinator
from .entity import DaejeonBusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DaejeonBusQuotaBinarySensor(hass.data[DOMAIN][entry.entry_id])])


class DaejeonBusQuotaBinarySensor(DaejeonBusEntity, BinarySensorEntity):
    """일일 요청 한도를 넘으면 on. 매일 0시(또는 그 API 조회 성공 시) off."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:api-off"

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("binary_sensor", "api_quota")
        self._attr_name = "API 호출 한도 초과"

    @property
    def available(self) -> bool:
        # 조회 실패와 상관없이 항상 상태를 보여준다
        return True

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.quota_exceeded)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        exceeded = self.coordinator.quota_exceeded
        return {
            "초과된 API": [API_NAMES.get(s, s) for s in exceeded],
            "발생 시각": min(exceeded.values()).isoformat() if exceeded else None,
            "안내": (
                "공공데이터포털 일일 요청 한도를 넘었습니다. 매일 0시에 초기화되며, "
                "그때까지 마지막으로 받은 정보를 보여주고 자동 조회를 쉽니다."
                if exceeded
                else None
            ),
        }
