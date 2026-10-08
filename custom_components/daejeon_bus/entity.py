"""대전 버스 공통 엔티티."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN, MANUFACTURER, VERSION
from .coordinator import DaejeonBusCoordinator


class DaejeonBusEntity(CoordinatorEntity[DaejeonBusCoordinator]):
    """정류소 단위 디바이스에 묶이는 엔티티."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaejeonBusCoordinator) -> None:
        super().__init__(coordinator)
        conf = coordinator.conf
        self._station_id = str(conf[CONF_STATION_ID])
        name = (
            conf.get(CONF_STATION_NAME)
            or (coordinator.data or {}).get("stop_name")
            or f"정류소 {self._station_id}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=f"{name} ({self._station_id})",
            manufacturer=MANUFACTURER,
            model="정류소 버스도착정보",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )
