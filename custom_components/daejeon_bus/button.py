"""대전 버스 버튼: 새로고침, 노선 센서 초기화, 정류장 이름 캐시 삭제."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .actions import async_clear_stop_cache, async_reset_route_entities
from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COMMUTE
from .coordinator import DaejeonBusBaseCoordinator
from .entity import DaejeonBusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DaejeonBusBaseCoordinator = hass.data[DOMAIN][entry.entry_id]
    buttons: list[ButtonEntity] = [
        DaejeonBusRefreshButton(coordinator),
        DaejeonBusClearCacheButton(coordinator),
    ]
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COMMUTE:
        buttons.append(DaejeonBusResetRoutesButton(coordinator, entry))
    async_add_entities(buttons)


class _AlwaysAvailableButton(DaejeonBusEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        # 조회가 실패해도 누를 수 있도록 항상 사용 가능
        return True


class DaejeonBusRefreshButton(_AlwaysAvailableButton):
    """누르면 즉시 다시 조회한다."""

    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("button", "refresh")
        self._attr_name = "새로고침"

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class DaejeonBusClearCacheButton(_AlwaysAvailableButton):
    """정류장 이름 캐시 파일 삭제 (모든 항목 공용). 다음 조회 때 다시 채워진다."""

    _attr_icon = "mdi:database-remove"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("button", "clear_cache")
        self._attr_name = "정류장 이름 캐시 삭제"

    async def async_press(self) -> None:
        await async_clear_stop_cache(self.hass)


class DaejeonBusResetRoutesButton(_AlwaysAvailableButton):
    """정류장 도착정보: 만들어진 노선별 센서를 모두 지우고, 지금 오는 노선만 다시 만든다."""

    _attr_icon = "mdi:bus-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DaejeonBusBaseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._set_ids("button", "reset_routes")
        self._attr_name = "노선 센서 초기화"

    async def async_press(self) -> None:
        await async_reset_route_entities(self.hass, self._entry)
