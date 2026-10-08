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

    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]) as mock,
        patch.object(DaejeonBusApi, "get_station_name") as lookup,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert mock.call_count == 1
        lookup.assert_not_called()  # 내장 목록에 있는 정류소는 API 호출 안 함

        state = hass.states.get("sensor.daejeon_bus_31770_3")
        assert state.state == "48초"
        assert state.attributes["잔여 정류장 수"] == 1
        assert state.attributes["최근 통과 정류소"] == "갈마육교"
        assert state.attributes["최근 통과 정류소 ID"] == "31910"
        assert state.attributes["운행 상태"] == "운행중"
        assert hass.states.get("sensor.daejeon_bus_31770_103").state == "5분 7초"
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": " dev-key ", CONF_STATION_ID: "31770"}
        )
    assert result["type"] == "create_entry"
    assert result["title"] == "갈마네거리 (31770)"
    assert result["data"] == {"api_key": "dev-key", CONF_STATION_ID: "31770"}


async def test_stop_name_lookup(hass, tmp_path):
    """CSV > 내장 목록 > 정류소정보 API 순으로 정류소 이름을 찾는다."""
    csv_path = tmp_path / "stops.csv"
    # 국토교통부 전국 버스정류장 위치정보 형식, CP949
    csv_path.write_bytes(
        (
            '"정류장번호","정류장명","위도","경도","정보수집일","모바일단축번호","도시코드","도시명","관리도시명"\n'
            '"DJB8001062","갈마육교(CSV)","36.35","127.37","2026-01-01","31910","25","대전광역시","대전"\n'
            '"XXX","다른도시","0","0","2026-01-01","31350","11","서울특별시","서울"\n'
        ).encode("cp949")
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "k", CONF_STATION_ID: "31770", "stops_csv": str(csv_path)},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    unknown = {**ITEMS[2], "MSG_TP": "03", "LAST_CAT": "3", "LAST_STOP_ID": "99999"}
    with (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=[ITEMS[0], ITEMS[1], unknown]),
        patch.object(DaejeonBusApi, "get_station_name", return_value="새정류소") as lookup,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    lookup.assert_called_once_with("99999")
    # CSV가 내장 목록보다 우선
    assert hass.states.get("sensor.daejeon_bus_31770_3").attributes["최근 통과 정류소"] == "갈마육교(CSV)"
    # 다른 도시 행은 무시되고 내장 목록 사용
    assert hass.states.get("sensor.daejeon_bus_31770_103").attributes["최근 통과 정류소"] == "KT인재개발원"
    # 둘 다 없으면 API
    state = hass.states.get("sensor.daejeon_bus_31770_116")
    assert state.attributes["최근 통과 정류소"] == "새정류소"
    assert state.attributes["메시지 유형"] == "몇분후 도착"
    assert state.attributes["첫/막차"] == "일반"
    assert state.attributes["노선유형"] == "간선"


def test_parse_bis_csv():
    from custom_components.daejeon_bus.stops import parse_csv

    text = "BUSSTOP_NM,BUS_STOP_ID,GPS_LATI\n대전광역시청,32350,36.35\n"
    assert parse_csv(text) == {"32350": "대전광역시청"}


def test_parse_daejeon_stop_status_csv():
    """대전광역시 시내버스 정류장 현황 형식 (관리번호 = arsId)."""
    from custom_components.daejeon_bus.stops import parse_csv

    text = (
        "관리번호,정류장 이름,시군구명,읍면동명,지번\n"
        "10010,대전역/중앙시장,동구,원동,51-1\n"
        "10020,원동네거리,동구,원동,85-28\n"
    )
    expected = {"10010": "대전역/중앙시장", "10020": "원동네거리"}
    assert parse_csv(text) == expected
    assert parse_csv(text.replace(",", "\t")) == expected
