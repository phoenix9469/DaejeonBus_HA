"""대전 버스 통합구성요소 테스트 (샘플 응답 사용)."""
from pathlib import Path
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daejeon_bus.api import DaejeonBusApi, parse_response
from custom_components.daejeon_bus.const import CONF_STATION_ID, DOMAIN

SAMPLE = (Path(__file__).parent / "fixture_31770.xml").read_text(encoding="utf-8")
ITEMS = parse_response(SAMPLE)


async def test_setup_and_refresh(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "dev-key", CONF_STATION_ID: "31770"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)

    with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]) as mock:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert mock.call_count == 1

        state = hass.states.get("sensor.daejeon_bus_31770_3")
        assert state.state == "48초"
        assert state.attributes["잔여 정류장 수"] == 1
        assert state.attributes["최근 통과 정류소"] == "31910"
        assert hass.states.get("sensor.daejeon_bus_31770_103").state == "5분 7초"
        assert hass.states.get("sensor.daejeon_bus_31770").state == "2"
        assert hass.states.get("sensor.daejeon_bus_31770_116") is None

    # 버튼을 누를 때만 조회 + 새 노선 센서 추가
    with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS) as mock:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        await hass.async_block_till_done()
        assert mock.call_count == 1
        state = hass.states.get("sensor.daejeon_bus_31770_116")
        assert state.state == "35분 10초"
        assert state.attributes["최근 통과 정류소"] is None

    # 노선이 사라지면 '도착정보 없음'
    with patch.object(DaejeonBusApi, "get_arrivals", return_value=[]):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("sensor.daejeon_bus_31770_3").state == "도착정보 없음"


async def test_config_flow(hass):
    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS),
        patch("custom_components.daejeon_bus.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": " dev-key ", CONF_STATION_ID: "31770"}
        )
    assert result["type"] == "create_entry"
    assert result["title"] == "갈마네거리 (31770)"
    assert result["data"] == {"api_key": "dev-key", CONF_STATION_ID: "31770"}
