"""대전 버스 (Daejeon Bus) for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COMMUTE
from .coordinator import CommuteCoordinator, DaejeonBusBaseCoordinator, StationCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: DaejeonBusBaseCoordinator
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COMMUTE:
        coordinator = CommuteCoordinator(hass, entry)
    else:
        coordinator = StationCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_auto_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
