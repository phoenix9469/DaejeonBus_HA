"""대전 버스 (Daejeon Bus) for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .actions import async_clear_stop_cache, async_reset_route_entities
from .card import async_register_card

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COMMUTE
from .coordinator import CommuteCoordinator, DaejeonBusBaseCoordinator, StationCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_CLEAR_STOP_CACHE = "clear_stop_name_cache"
SERVICE_RESET_ROUTE_ENTITIES = "reset_route_entities"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """대시보드 카드 등록 + 서비스 등록 (캐시 파일 삭제, 노선 센서 초기화)."""
    await async_register_card(hass)

    async def _clear_cache(call: ServiceCall) -> ServiceResponse:
        removed = await async_clear_stop_cache(hass)
        return {"removed_stops": removed}

    async def _reset_routes(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COMMUTE
            and (entry_id is None or e.entry_id == entry_id)
        ]
        if entry_id and not entries:
            raise ServiceValidationError(f"정류장 도착정보 항목이 아닙니다: {entry_id}")
        removed = {}
        for entry in entries:
            removed[entry.title] = await async_reset_route_entities(hass, entry)
        return {"removed_entities": removed}

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_STOP_CACHE,
        _clear_cache,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_ROUTE_ENTITIES,
        _reset_routes,
        schema=vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


# 이전 버전에서 만들었다가 없앤 엔티티 (unique_id 끝부분)
_REMOVED_SUFFIXES = ("_leave_in", "_leave_now", "_second_minutes")


def _remove_obsolete_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.unique_id.endswith(_REMOVED_SUFFIXES):
            ent_reg.async_remove(reg_entry.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # async_setup 시점에 프런트엔드가 준비되지 않았던 경우 대비 (이미 등록됐으면 아무것도 안 함)
    await async_register_card(hass)
    coordinator: DaejeonBusBaseCoordinator
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COMMUTE:
        coordinator = CommuteCoordinator(hass, entry)
    else:
        coordinator = StationCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_auto_refresh()

    _remove_obsolete_entities(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
