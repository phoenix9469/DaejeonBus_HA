"""대시보드 카드 자동 등록 + 카드가 쓰는 센서 속성."""
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daejeon_bus.api import DaejeonBusApi
from custom_components.daejeon_bus.card import CARD_FILE, CARD_URL, async_register_card
from custom_components.daejeon_bus.const import DOMAIN

from .helpers import fake_route_stops
from .test_init import ITEMS


async def test_card_registered_when_frontend_available(hass):
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    urls = MagicMock()
    hass.data[DATA_EXTRA_MODULE_URL] = urls

    assert await async_register_card(hass)
    (paths,), _ = hass.http.async_register_static_paths.call_args
    assert paths[0].url_path == CARD_URL and paths[0].path == str(CARD_FILE)
    (url,), _ = urls.add.call_args
    assert url.startswith(f"{CARD_URL}?v=")
    # 두 번 불러도 한 번만 등록
    assert await async_register_card(hass)
    assert hass.http.async_register_static_paths.call_count == 1


async def test_card_skipped_without_frontend(hass):
    assert not await async_register_card(hass)
    assert CARD_FILE.exists()


async def test_summary_sensor_has_card_attributes(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]),
        patch.object(DaejeonBusApi, "get_route_stops", side_effect=fake_route_stops),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    attrs = hass.states.get("sensor.daejeon_bus_31770").attributes
    assert attrs["새로고침 버튼"] == "button.daejeon_bus_31770_refresh"
    assert attrs["마지막 조회"]


async def test_card_registration_retries_after_start(hass):
    """frontend 가 늦게 준비되면 HA 시작 완료 후 다시 등록한다."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    assert not await async_register_card(hass)  # 아직 frontend 없음
    assert hass.http.async_register_static_paths.call_count == 1  # 파일 서빙은 먼저

    urls = MagicMock()
    hass.data[DATA_EXTRA_MODULE_URL] = urls
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    urls.add.assert_called_once()
    assert hass.http.async_register_static_paths.call_count == 1
