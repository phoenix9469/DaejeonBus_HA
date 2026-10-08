"""대전 버스 새로고침 버튼."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from .coordinator import DaejeonBusBaseCoordinator
from .entity import DaejeonBusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DaejeonBusBaseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DaejeonBusRefreshButton(coordinator)])


class DaejeonBusRefreshButton(DaejeonBusEntity, ButtonEntity):
    """누르면 즉시 다시 조회한다."""

    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: DaejeonBusBaseCoordinator) -> None:
        super().__init__(coordinator)
        self._set_ids("button", "refresh")
        self._attr_name = "새로고침"

    @property
    def available(self) -> bool:
        # 조회가 실패해도 다시 시도할 수 있도록 항상 사용 가능
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
