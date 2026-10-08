"""대전 버스 통합구성요소 테스트 (샘플 응답 사용)."""
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

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

    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]) as mock,
        patch.object(
            DaejeonBusApi,
            "get_station_name",
            side_effect=lambda a: {"31910": "갈마육교", "31350": "KT인재개발원"}[a],
        ) as lookup,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert mock.call_count == 1
        assert lookup.call_count == 2  # 캐시 파일이 비어 있으니 API로 조회

        state = hass.states.get("sensor.daejeon_bus_31770_3")
        assert state.state == "곧 도착 (1정류장 전)"  # 기본 기준 3분 이하
        assert state.attributes["운행 상태"] == "곧 도착"
        assert state.attributes["도착예정시간"] == "48초"
        assert state.attributes["잔여 정류장 수"] == 1
        assert state.attributes["최근 통과 정류소"] == "갈마육교"
        assert state.attributes["최근 통과 정류소 ID"] == "31910"

        state = hass.states.get("sensor.daejeon_bus_31770_103")
        assert state.state == "5분 7초 (4정류장 전)"
        assert state.attributes["운행 상태"] == "운행중"
        assert hass.states.get("sensor.daejeon_bus_31770").state == "2"
        assert hass.states.get("sensor.daejeon_bus_31770_116") is None

    # 버튼을 누를 때만 조회 + 새 노선 센서 추가
    entering = {**ITEMS[0], "MSG_TP": "06"}
    with patch.object(
        DaejeonBusApi, "get_arrivals", return_value=[entering, *ITEMS[1:]]
    ) as mock:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        await hass.async_block_till_done()
        assert mock.call_count == 1
        assert hass.states.get("sensor.daejeon_bus_31770_3").state == "진입중"
        state = hass.states.get("sensor.daejeon_bus_31770_116")
        assert state.state == "운행대기"
        assert state.attributes["도착예정시간"] is None
        station = hass.states.get("sensor.daejeon_bus_31770")
        assert station.state == "2"  # 운행대기 제외
        assert [b["노선"] for b in station.attributes["버스 목록"]] == ["3", "103", "116"]

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
        assert result["type"] == "menu"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "station"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": " dev-key ", CONF_STATION_ID: "31770"}
        )
    assert result["type"] == "create_entry"
    assert result["title"] == "갈마네거리 (31770)"
    assert result["data"] == {
        "entry_type": "station",
        "api_key": "dev-key",
        CONF_STATION_ID: "31770",
    }


async def test_stop_name_lookup(hass, hass_storage):
    """캐시 파일에 있으면 그대로 쓰고, 없을 때만 정류소정보 API로 조회해 파일에 저장한다."""
    hass_storage["daejeon_bus_stop_names"] = {
        "version": 1,
        "key": "daejeon_bus_stop_names",
        "data": {"stops": {"31910": "갈마육교(캐시)"}},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data={"api_key": "k", CONF_STATION_ID: "31770"}, unique_id="31770"
    )
    entry.add_to_hass(hass)
    unknown = {**ITEMS[2], "MSG_TP": "03", "LAST_CAT": "3", "LAST_STOP_ID": "99999"}
    items = [ITEMS[0], ITEMS[1], unknown]  # LAST_STOP_ID: 31910, 31350, 99999

    async def station_name(ars_id):
        return {"31350": "KT인재개발원", "99999": "새정류소"}[ars_id]

    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=items),
        patch.object(DaejeonBusApi, "get_station_name", side_effect=station_name) as lookup,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # 캐시에 있는 31910은 조회하지 않음
        assert sorted(c.args[0] for c in lookup.call_args_list) == ["31350", "99999"]

        attrs = lambda e: hass.states.get(e).attributes  # noqa: E731
        assert attrs("sensor.daejeon_bus_31770_3")["최근 통과 정류소"] == "갈마육교(캐시)"
        assert attrs("sensor.daejeon_bus_31770_103")["최근 통과 정류소"] == "KT인재개발원"
        state = hass.states.get("sensor.daejeon_bus_31770_116")
        assert state.attributes["최근 통과 정류소"] == "새정류소"
        assert state.attributes["메시지 유형"] == "몇분후 도착"
        assert state.attributes["첫/막차"] == "일반"
        assert state.attributes["노선유형"] == "간선"

        # 다시 새로고침해도 이미 찾은 이름은 다시 조회하지 않음
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        assert lookup.call_count == 2

    # 파일에 저장 (지연 저장 시간 경과)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    saved = hass_storage["daejeon_bus_stop_names"]["data"]["stops"]
    assert saved == {"31350": "KT인재개발원", "31910": "갈마육교(캐시)", "99999": "새정류소"}


async def test_stop_name_api_unavailable(hass):
    """API로 이름을 못 찾으면 정류소 번호를 그대로 보여주고, 재시작 전까지 다시 시도하지 않는다."""
    from custom_components.daejeon_bus.api import DaejeonBusError

    entry = MockConfigEntry(
        domain=DOMAIN, data={"api_key": "k", CONF_STATION_ID: "31770"}, unique_id="31770"
    )
    entry.add_to_hass(hass)
    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:1]),
        patch.object(
            DaejeonBusApi, "get_station_name", side_effect=DaejeonBusError("403")
        ) as lookup,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        state = hass.states.get("sensor.daejeon_bus_31770_3")
        assert state.attributes["최근 통과 정류소"] == "31910"
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        assert lookup.call_count == 1



async def test_soon_threshold_option(hass):
    """'곧 도착' 기준을 바꾸거나 0으로 끌 수 있다."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "k", CONF_STATION_ID: "31770"},
        options={"soon_minutes": 0},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.daejeon_bus_31770_3").state == "48초 (1정류장 전)"

        hass.config_entries.async_update_entry(entry, options={"soon_minutes": 6})
        await hass.async_block_till_done()  # 옵션 변경 시 다시 로드
        assert hass.states.get("sensor.daejeon_bus_31770_3").state == "곧 도착 (1정류장 전)"
        assert hass.states.get("sensor.daejeon_bus_31770_103").state == "곧 도착 (4정류장 전)"
