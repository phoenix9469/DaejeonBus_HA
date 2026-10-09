"""삭제/초기화 동작 (버튼과 서비스가 공용으로 사용)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_STATION_ID, DOMAIN
from .coordinator import CommuteCoordinator
from .stops import get_stop_cache

_LOGGER = logging.getLogger(__name__)


async def async_clear_stop_cache(hass: HomeAssistant) -> int:
    """정류장 이름 캐시 파일 삭제. 이름은 다음 조회 때 API로 다시 채워진다."""
    count = await get_stop_cache(hass).async_clear()
    for coordinator in hass.data.get(DOMAIN, {}).values():
        if isinstance(coordinator, CommuteCoordinator):
            coordinator.async_invalidate_stops()
    return count


def route_entity_prefix(entry: ConfigEntry) -> str:
    return f"{DOMAIN}_{entry.data[CONF_STATION_ID]}_route_"


async def async_reset_route_entities(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """정류장 도착정보 항목이 만든 노선별 센서를 모두 지우고 항목을 다시 불러온다.

    다시 불러오면 지금 도착정보에 있는 노선(또는 대상 버스 목록)만 새로 만들어진다.
    """
    prefix = route_entity_prefix(entry)
    ent_reg = er.async_get(hass)
    removed = 0
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == "sensor" and reg_entry.unique_id.startswith(prefix):
            ent_reg.async_remove(reg_entry.entity_id)
            removed += 1
    _LOGGER.info("%s: 노선 센서 %d개를 삭제했습니다", entry.title, removed)
    # 버튼에서 호출될 수 있으므로 다시 불러오기는 예약만 한다
    hass.config_entries.async_schedule_reload(entry.entry_id)
    return removed
