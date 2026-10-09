"""노선으로 조회 테스트 (213번 노선 실제 응답 사용)."""
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.util import dt as dt_util

from custom_components.daejeon_bus import commute
from custom_components.daejeon_bus.api import DaejeonBusApi, parse_response
from custom_components.daejeon_bus.const import DOMAIN
from custom_components.daejeon_bus.schedule import in_window

HERE = Path(__file__).parent
ROUTE_STOPS = parse_response((HERE / "fixture_route_30300146.xml").read_text(encoding="utf-8"))
POSITIONS = parse_response((HERE / "fixture_buspos_30300146.xml").read_text(encoding="utf-8"))
ROUTE_CD = "30300146"
# 내 정류장 갈마네거리(31770)에서 본 213번 도착정보: 3정류장 전 버스(아이빌딩)가 5분 뒤 도착
ARRIVALS = [
    {
        "ROUTE_CD": ROUTE_CD,
        "ROUTE_NO": "213",
        "DESTINATION": "원내동공영차고지",
        "CAR_REG_NO": "대전75자2716",
        "EXTIME_SEC": "300",
        "MSG_TP": "03",
        "STOP_NAME": "갈마네거리",
    }
]


def _my_stop():
    stops = commute.parse_route_stops(ROUTE_STOPS)
    (my_stop,) = commute.find_stops(stops, "31770")
    return stops, my_stop


def test_approaching_buses():
    stops, my_stop = _my_stop()
    assert (my_stop.seq, my_stop.dist) == (64, 31283)

    buses = commute.approaching_buses(stops, my_stop, POSITIONS)
    # 이미 지나간 버스(42694, 38747)는 제외, 가까운 순
    assert [(b["stops_away"], b["current_stop"]) for b in buses] == [
        (3, "아이빌딩"),
        (9, "동아연필"),
        (31, "시청역"),
        (33, "SK브로드밴드"),
        (42, "천년나무11단지"),
        (55, "원앙4단지"),
    ]
    assert buses[0]["meters_away"] == 31283 - 29819


def test_first_bus_eta():
    stops, my_stop = _my_stop()
    buses = commute.approaching_buses(stops, my_stop, POSITIONS)
    assert commute.first_bus_eta(buses, ARRIVALS, ROUTE_CD) == 300

    # 지금 오는 버스만 도착예정시간, 나머지는 추정하지 않음
    assert buses[0]["eta_seconds"] == 300
    assert all(b["eta_seconds"] is None for b in buses[1:])



def test_first_bus_eta_plate_mismatch_and_no_arrival():
    stops, my_stop = _my_stop()
    buses = commute.approaching_buses(stops, my_stop, POSITIONS)
    # 차량번호가 다르면(두 API 갱신 시점 차이) 이 노선의 가장 빠른 도착정보 사용
    other = [{**ARRIVALS[0], "CAR_REG_NO": "대전75자0000", "EXTIME_SEC": "280"}]
    assert commute.first_bus_eta(buses, other, ROUTE_CD) == 280
    # 다른 노선이나 운행대기는 무시
    ignored = [
        {**ARRIVALS[0], "ROUTE_CD": "30300001"},
        {**ARRIVALS[0], "MSG_TP": "07"},
    ]
    assert commute.first_bus_eta(buses, ignored, ROUTE_CD) is None
    assert buses[0]["eta_seconds"] is None


def test_in_window():
    weekdays = ["mon", "tue", "wed", "thu", "fri"]
    thu_0730 = datetime(2026, 10, 8, 7, 30)  # 목요일
    assert in_window(thu_0730, time(7), time(9), weekdays)
    assert not in_window(thu_0730.replace(hour=9, minute=1), time(7), time(9), weekdays)
    assert not in_window(datetime(2026, 10, 10, 7, 30), time(7), time(9), weekdays)  # 토요일
    # 자정을 넘는 구간: 금 23:00 ~ 토 01:00
    assert in_window(datetime(2026, 10, 10, 0, 30), time(23), time(1), weekdays)
    assert not in_window(datetime(2026, 10, 11, 0, 30), time(23), time(1), weekdays)


def _patch_api(arrivals=ARRIVALS):
    return (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=arrivals),
        patch.object(DaejeonBusApi, "get_route_stops", return_value=ROUTE_STOPS),
        patch.object(DaejeonBusApi, "get_bus_positions", return_value=POSITIONS),
    )


async def test_commute_config_flow(hass):
    p1, p2, p3 = _patch_api()
    with p1, p2, p3, patch(
        "custom_components.daejeon_bus.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "commute"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "station_id": "31770"}
        )
        assert result["step_id"] == "commute_route"
        # 노선번호로 입력해도 노선 ID로 변환
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"route_cd": "213"}
        )
    assert result["type"] == "create_entry"
    assert result["title"] == "213번 → 갈마네거리"
    assert result["data"] == {
        "entry_type": "commute",
        "api_key": "k",
        "station_id": "31770",
        "route_cd": ROUTE_CD,
        "route_no": "213",
        "stop_seq": 64,
    }


async def test_commute_config_flow_direction(hass):
    """같은 정류장을 두 번 지나면 방향을 고른다 (대한통운종점 50710: 45, 47번째)."""
    p1, p2, p3 = _patch_api(arrivals=[])
    with p1, p2, p3:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "commute"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "station_id": "50710"}
        )
        # 도착정보가 없으면 노선 ID 직접 입력
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"route_cd": ROUTE_CD}
        )
        assert result["step_id"] == "commute_direction"
        labels = [o["label"] for o in result["data_schema"].schema["stop_seq"].config["options"]]
        assert labels == ["45번째 정류장 (다음: 대한통운종점)", "47번째 정류장 (다음: 대한통운)"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"stop_seq": "47"}
        )
        assert result["type"] == "create_entry"
        assert result["data"]["stop_seq"] == 47


async def test_commute_config_flow_stop_not_on_route(hass):
    p1, p2, p3 = _patch_api()
    with p1, p2, p3:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "commute"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "station_id": "99999"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"route_cd": ROUTE_CD}
        )
    assert result["errors"] == {"route_cd": "stop_not_on_route"}


def _entry(**options):
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "commute",
            "api_key": "k",
            "station_id": "31770",
            "route_cd": ROUTE_CD,
            "route_no": "213",
            "stop_seq": 64,
        },
        options=options,
        unique_id=f"commute_{ROUTE_CD}_64",
    )


async def test_commute_entities(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    p1, p2, p3 = _patch_api()
    with p1, p2 as stops_mock, p3 as pos_mock:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        prefix = "daejeon_bus_commute_213_31770"
        assert hass.states.get(f"sensor.{prefix}_first_stops").state == "3"
        assert hass.states.get(f"sensor.{prefix}_first_minutes").state == "5분 0초"
        first = hass.states.get(f"sensor.{prefix}_first_minutes").attributes
        assert first["도착예정(초)"] == 300 and first["도착예정(분)"] == 5.0
        assert first["현재 정류장"] == "아이빌딩" and first["남은 거리(m)"] == 1464
        second = hass.states.get(f"sensor.{prefix}_second_stops")
        assert second.state == "9"
        assert "도착예정시간" not in second.attributes  # 두 번째 버스는 정류장 수만
        assert hass.states.get(f"sensor.{prefix}_second_minutes") is None
        # 출발 안내 기능은 없음
        assert hass.states.get(f"sensor.{prefix}_leave_in") is None
        assert hass.states.get(f"binary_sensor.{prefix}_leave_now") is None
        summary = hass.states.get(f"sensor.{prefix}")
        assert summary.state == "6"  # 오는 버스 6대
        assert summary.attributes["내 정류장"] == "갈마네거리"
        assert len(summary.attributes["버스 목록"]) == 6
        assert hass.states.get(f"button.{prefix}_refresh") is not None

        # 노선 경유 정류소 이름(91개 중 고유 arsId)은 공용 정류소 이름 캐시에 저장
        from custom_components.daejeon_bus.stops import get_stop_cache

        cache = get_stop_cache(hass)
        assert cache.get("31770") == "갈마네거리"
        assert cache.get("32190") == "아이빌딩"

        # 버튼을 누르면 위치만 다시 조회 (정류소 목록은 캐시)
        await hass.services.async_call(
            "button", "press", {"entity_id": f"button.{prefix}_refresh"}, blocking=True
        )
        assert pos_mock.call_count == 2
        assert stops_mock.call_count == 1

        # 자동 조회는 기본 꺼짐
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
        await hass.async_block_till_done()
        assert pos_mock.call_count == 2


async def test_commute_removes_obsolete_entities(hass):
    """이전 버전의 출발 안내 엔티티는 정리된다."""
    from homeassistant.helpers import entity_registry as er

    entry = _entry()
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    for platform, suffix in (("sensor", "leave_in"), ("binary_sensor", "leave_now")):
        ent_reg.async_get_or_create(
            platform, DOMAIN, f"{DOMAIN}_commute_{ROUTE_CD}_64_{suffix}", config_entry=entry
        )
    p1, p2, p3 = _patch_api()
    with p1, p2, p3:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    left = {e.unique_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}
    assert not any(u.endswith(("_leave_in", "_leave_now")) for u in left)


async def test_commute_without_arrival_info(hass):
    """도착정보가 없으면 정류장 수만 보여준다."""
    entry = _entry()
    entry.add_to_hass(hass)
    p1, p2, p3 = _patch_api(arrivals=[])
    with p1, p2, p3:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    prefix = "daejeon_bus_commute_213_31770"
    assert hass.states.get(f"sensor.{prefix}_first_stops").state == "3"
    assert hass.states.get(f"sensor.{prefix}_first_minutes").state == "unknown"
    assert hass.states.get(f"sensor.{prefix}").state == "6"


async def test_auto_refresh_option(hass):
    """자동 조회를 켜면 시간대 안에서 주기적으로 조회한다."""
    entry = _entry(
        auto_refresh=True,
        auto_start="00:00:00",
        auto_end="00:00:00",  # 같으면 하루 종일
        auto_weekdays=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        auto_interval=60,
    )
    entry.add_to_hass(hass)
    p1, p2, p3 = _patch_api()
    with p1, p2, p3 as pos_mock:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert pos_mock.call_count == 1

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
        await hass.async_block_till_done()
        assert pos_mock.call_count == 2

        # 시간대 밖이면 조회하지 않음
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "auto_weekdays": []}
        )
        await hass.async_block_till_done()
        calls = pos_mock.call_count
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=200))
        await hass.async_block_till_done()
        assert pos_mock.call_count == calls
