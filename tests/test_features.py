"""옵션(대상 버스 해제, 자동 조회 예상 호출), 캐시 삭제, 노선 센서 초기화 테스트."""
from pathlib import Path
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.helpers import entity_registry as er

from custom_components.daejeon_bus.api import DaejeonBusApi, parse_response
from custom_components.daejeon_bus.const import ARRIVE_URL, BUS_POS_URL, DOMAIN
from custom_components.daejeon_bus.schedule import estimate_auto_calls, format_estimate

HERE = Path(__file__).parent
ITEMS = parse_response((HERE / "fixture_31770.xml").read_text(encoding="utf-8"))
NAMES = {"31910": "갈마육교", "31350": "KT인재개발원"}
COMMUTE = ({"busposinfo": 1, "arrive": 1}, {"busRouteInfo": 1})
STATION = ({"arrive": 1}, {})


def _patches():
    return (
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]),
        patch.object(DaejeonBusApi, "get_station_name", side_effect=lambda a: NAMES.get(a)),
    )


def _route_sensors(hass, entry):
    ent_reg = er.async_get(hass)
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if "_route_" in e.unique_id
    )


# ---- 예상 API 호출 수 ----


def test_estimate_weekday_morning():
    conf = {
        "auto_refresh": True,
        "auto_start": "07:00:00",
        "auto_end": "09:00:00",
        "auto_weekdays": ["mon", "tue", "wed", "thu", "fri"],
        "auto_interval": 60,
    }
    est = estimate_auto_calls(conf, *COMMUTE)
    # 2시간 / 60초 = 120회 + 시작 시각 1회
    assert est["refreshes_per_day"] == 121
    assert est["per_day"] == {"busposinfo": 121, "arrive": 121, "busRouteInfo": 1}
    assert est["total_per_day"] == 243
    assert est["total_per_week"] == 243 * 5
    assert est["busiest_percent"] == 12.1
    text = format_estimate(est)
    assert "하루 약 **121회**" in text and "⚠️" not in text


def test_estimate_all_day_over_limit_and_off():
    conf = {"auto_refresh": True, "auto_start": "00:00", "auto_end": "00:00",
            "auto_weekdays": ["sat"], "auto_interval": 30}
    est = estimate_auto_calls(conf, *STATION)
    assert est["per_day"] == {"arrive": 2880}
    assert "⚠️" in format_estimate(est)

    off = estimate_auto_calls({**conf, "auto_refresh": False}, *STATION)
    assert off["total_per_day"] == 0 and not off["enabled"]
    assert "꺼져" in format_estimate(off)
    # 요일을 하나도 고르지 않으면 0
    assert estimate_auto_calls({**conf, "auto_weekdays": []}, *STATION)["total_per_day"] == 0


def test_api_counts_calls_per_service():
    api = DaejeonBusApi(None, "k")
    api._count(ARRIVE_URL)
    api._count(ARRIVE_URL)
    api._count(BUS_POS_URL)
    assert api.calls_today == {"arrive": 2, "busposinfo": 1}


# ---- 옵션 ----


async def test_options_clear_include_buses(hass):
    """대상 버스를 지우면(화면에서 칸을 비우면 키가 빠짐) 전체 노선으로 돌아간다."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770", "include_buses": "3"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    p1, p2 = _patches()
    with p1, p2:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.daejeon_bus_31770_103") is None

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"api_key": "k"}  # include_buses 없음 = 칸을 비움
        )
        assert result["type"] == "create_entry"
        assert entry.options["include_buses"] == ""
        await hass.async_block_till_done()
        assert hass.states.get("sensor.daejeon_bus_31770_3") is not None
        assert hass.states.get("sensor.daejeon_bus_31770_103") is not None

        # 다시 대상 버스를 지정하면 빠진 노선 센서는 정리
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"api_key": "k", "include_buses": "103"}
        )
        await hass.async_block_till_done()
        assert _route_sensors(hass, entry) == ["sensor.daejeon_bus_31770_103"]


async def test_options_auto_confirm_step(hass):
    """자동 조회를 켜면 저장 전에 예상 호출 수를 보여주는 확인 단계가 있다."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    p1, p2 = _patches()
    with p1, p2:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert "꺼져" in result["description_placeholders"]["estimate"]
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "api_key": "k",
                "auto_refresh": True,
                "auto_start": "07:00:00",
                "auto_end": "09:00:00",
                "auto_weekdays": ["mon", "tue", "wed", "thu", "fri"],
                "auto_interval": 60,
            },
        )
        assert result["step_id"] == "auto_confirm"
        assert "121회" in result["description_placeholders"]["estimate"]
        assert not entry.options  # 아직 저장 전
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
        assert result["type"] == "create_entry"
        assert entry.options["auto_refresh"] is True
        await hass.async_block_till_done()

        usage = hass.states.get("sensor.daejeon_bus_31770_api_usage")
        assert usage.state == "121"
        assert usage.attributes["API별 하루 예상"] == {"도착정보 (arrive)": 121}
        assert usage.attributes["자동 조회"] == "켜짐"


# ---- 삭제 기능 ----


async def test_clear_stop_name_cache(hass, hass_storage):
    hass_storage["daejeon_bus_stop_names"] = {
        "version": 1,
        "key": "daejeon_bus_stop_names",
        "data": {"stops": {"31910": "갈마육교", "11111": "옛 정류장"}},
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    p1, p2 = _patches()
    with p1, p2 as lookup:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.services.async_call(
            DOMAIN, "clear_stop_name_cache", {}, blocking=True, return_response=True
        )
        assert result == {"removed_stops": 3}  # 파일 2개 + API로 찾은 31350
        assert "daejeon_bus_stop_names" not in hass_storage

        # 버튼으로도 삭제, 이후 새로고침하면 API로 다시 채움
        lookup.reset_mock()
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_clear_cache"}, blocking=True
        )
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_refresh"}, blocking=True
        )
        assert sorted(c.args[0] for c in lookup.call_args_list) == ["31350", "31910"]


async def test_reset_route_entities(hass):
    """노선 센서 초기화: 예전에 만들어진 노선 센서를 지우고 지금 오는 노선만 다시 만든다."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770"},
        unique_id="31770",
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, f"{DOMAIN}_31770_route_999", config_entry=entry,
        suggested_object_id="daejeon_bus_31770_999",
    )
    p1, p2 = _patches()
    with p1, p2:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert "sensor.daejeon_bus_31770_999" in _route_sensors(hass, entry)

        await hass.services.async_call(
            "button", "press", {"entity_id": "button.daejeon_bus_31770_reset_routes"}, blocking=True
        )
        await hass.async_block_till_done()
        assert _route_sensors(hass, entry) == [
            "sensor.daejeon_bus_31770_103",
            "sensor.daejeon_bus_31770_3",
        ]

        # 서비스로도 가능 (응답: 항목별 삭제 수)
        result = await hass.services.async_call(
            DOMAIN, "reset_route_entities", {"config_entry_id": entry.entry_id},
            blocking=True, return_response=True,
        )
        await hass.async_block_till_done()
        assert result == {"removed_entities": {entry.title: 2}}
        assert hass.states.get("sensor.daejeon_bus_31770_3") is not None
