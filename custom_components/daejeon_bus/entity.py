"""대전 버스 공통 엔티티."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, VERSION
from .coordinator import DaejeonBusBaseCoordinator


class DaejeonBusEntity(CoordinatorEntity[DaejeonBusBaseCoordinator]):
    """항목(정류소 또는 노선으로 조회) 단위 기기에 묶이는 엔티티."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        # unique_id용 고정 키 / entity_id용 읽기 쉬운 키
        self._key = coordinator.unique_key
        self._slug = coordinator.slug
        # 정류소 항목은 key == arsId (기존 unique_id 유지)
        self._station_id = coordinator.unique_key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.unique_key)},
            name=coordinator.device_name,
            manufacturer=MANUFACTURER,
            model=coordinator.device_model,
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _set_ids(self, platform: str, suffix: str | None) -> None:
        """unique_id = daejeon_bus_<key>[_suffix], entity_id = <platform>.daejeon_bus_<slug>[_suffix]."""
        tail = f"_{suffix}" if suffix else ""
        self._attr_unique_id = f"{DOMAIN}_{self._key}{tail}"
        self.entity_id = f"{platform}.{DOMAIN}_{self._slug}{tail}"
