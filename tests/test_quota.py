"""공공데이터포털 일일 요청 한도 초과 처리."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.util import dt as dt_util

from custom_components.daejeon_bus.api import (
    DaejeonBusApi,
    DaejeonBusQuotaError,
    parse_response,
)
from custom_components.daejeon_bus.const import DOMAIN

from .helpers import fake_route_stops
from .test_commute import ARRIVALS, POSITIONS, ROUTE_CD, ROUTE_STOPS
from .test_init import ITEMS

# 사용자 로그에 찍힌 실제 응답
QUOTA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse>
  <cmmMsgHeader>
    <errMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</errMsg>
    <returnAuthMsg>일일 서비스 요청제한 횟수 초과 에러</returnAuthMsg>
    <returnReasonCode>22</returnReasonCode>
  </cmmMsgHeader>
</OpenAPI_ServiceResponse>"""


def quota(service="arrive"):
    return DaejeonBusQuotaError("일일 요청 한도 초과 (HTTP 429)", service)


def test_parse_quota_response():
    with pytest.raises(DaejeonBusQuotaError):
        parse_response(QUOTA_XML)


class _FakeResp:
    def __init__(self, status, text):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, status, text):
        self.status, self.text = status, text

    def get(self, url):
        return _FakeResp(self.status, self.text)


async def test_http_429_is_quota_error_with_service():
    api = DaejeonBusApi(_FakeSession(429, QUOTA_XML), "k")
    with pytest.raises(DaejeonBusQuotaError) as err:
        await api.get_arrivals("31770")
    assert err.value.service == "arrive"
    # 200 으로 와도 본문이 한도 초과면 같은 오류
    api = DaejeonBusApi(_FakeSession(200, QUOTA_XML), "k")
    with pytest.raises(DaejeonBusQuotaError) as err:
        await api.get_bus_positions(ROUTE_CD)
    assert err.value.service == "busposinfo"


def _station_entry(**options):
    return MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "station", "api_key": "k", "station_id": "31770"},
        options=options,
        unique_id="31770",
    )


async def _press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def test_station_quota_keeps_last_data_and_turns_sensor_on(hass):
    entry = _station_entry(
        auto_refresh=True, auto_start="00:00:00", auto_end="00:00:00",
        auto_weekdays=["mon", "tue", "wed", "thu", "fri", "sat", "sun"], auto_interval=60,
    )
    entry.add_to_hass(hass)
    with patch.object(DaejeonBusApi, "get_route_stops", side_effect=fake_route_stops):
        with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        quota_sensor = "binary_sensor.daejeon_bus_31770_api_quota"
        assert hass.states.get(quota_sensor).state == "off"

        with patch.object(DaejeonBusApi, "get_arrivals", side_effect=quota()) as arr:
            await _press(hass, "button.daejeon_bus_31770_refresh")
            # 엔티티는 사용 가능, 마지막 정보 유지
            assert hass.states.get("sensor.daejeon_bus_31770_3").state != "unavailable"
            assert hass.states.get("sensor.daejeon_bus_31770_3").attributes["도착예정시간"] == "48초"
            q = hass.states.get(quota_sensor)
            assert q.state == "on"
            assert q.attributes["초과된 API"] == ["도착정보 (arrive)"]
            assert "0시" in q.attributes["안내"]
            summary = hass.states.get("sensor.daejeon_bus_31770")
            assert summary.attributes["API 한도 초과"] == ["도착정보 (arrive)"]

            # 한도 초과 중에는 자동 조회를 쉰다
            calls = arr.call_count
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
            await hass.async_block_till_done()
            assert arr.call_count == calls

        # 0시가 지나면 조회하지 않아도 꺼짐
        tomorrow = dt_util.start_of_local_day() + timedelta(days=1, seconds=6)
        with patch("homeassistant.util.dt.now", return_value=tomorrow):
            async_fire_time_changed(hass, tomorrow)
            await hass.async_block_till_done()
        assert hass.states.get(quota_sensor).state == "off"


async def test_quota_cleared_when_api_works_again(hass):
    entry = _station_entry()
    entry.add_to_hass(hass)
    with patch.object(DaejeonBusApi, "get_route_stops", side_effect=fake_route_stops):
        with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        with patch.object(DaejeonBusApi, "get_arrivals", side_effect=quota()):
            await _press(hass, "button.daejeon_bus_31770_refresh")
        assert hass.states.get("binary_sensor.daejeon_bus_31770_api_quota").state == "on"
        with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:2]):
            await _press(hass, "button.daejeon_bus_31770_refresh")
        assert hass.states.get("binary_sensor.daejeon_bus_31770_api_quota").state == "off"
        assert hass.states.get("sensor.daejeon_bus_31770").attributes["API 한도 초과"] == []


async def test_station_setup_while_quota_exceeded(hass):
    """처음 불러올 때부터 한도 초과여도 항목은 올라오고 센서가 on."""
    entry = _station_entry()
    entry.add_to_hass(hass)
    with patch.object(DaejeonBusApi, "get_arrivals", side_effect=quota()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.daejeon_bus_31770_api_quota").state == "on"
    assert hass.states.get("sensor.daejeon_bus_31770").state == "0"


async def test_stop_name_lookup_retries_after_quota(hass):
    """정류장 이름 조회가 한도 초과면 포기하지 않고 다음에 다시 시도한다."""
    entry = _station_entry()
    entry.add_to_hass(hass)
    with patch.object(DaejeonBusApi, "get_arrivals", return_value=ITEMS[:1]):
        with patch.object(DaejeonBusApi, "get_route_stops", side_effect=quota("busRouteInfo")):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        q = hass.states.get("binary_sensor.daejeon_bus_31770_api_quota")
        assert q.state == "on" and q.attributes["초과된 API"] == ["노선정류장 (busRouteInfo)"]
        assert hass.states.get("sensor.daejeon_bus_31770_3").attributes["최근 통과 정류소"] == "31910"

        with patch.object(DaejeonBusApi, "get_route_stops", side_effect=fake_route_stops) as rs:
            await _press(hass, "button.daejeon_bus_31770_refresh")
        rs.assert_called_once_with("30300104")
        assert hass.states.get("sensor.daejeon_bus_31770_3").attributes["최근 통과 정류소"] == "갈마육교"


def _commute_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "commute", "api_key": "k", "station_id": "31770",
              "route_cd": ROUTE_CD, "route_no": "213", "stop_seq": 64},
        unique_id=f"commute_{ROUTE_CD}_64",
    )


async def test_commute_quota(hass):
    entry = _commute_entry()
    entry.add_to_hass(hass)
    prefix = "daejeon_bus_commute_213_31770"
    with (
        patch.object(DaejeonBusApi, "get_route_stops", return_value=ROUTE_STOPS),
        patch.object(DaejeonBusApi, "get_arrivals", return_value=ARRIVALS),
        patch.object(DaejeonBusApi, "get_bus_positions", return_value=POSITIONS),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(f"binary_sensor.{prefix}_api_quota").state == "off"

    # 버스 위치 한도 초과: 마지막 정보 유지
    with patch.object(DaejeonBusApi, "get_bus_positions", side_effect=quota("busposinfo")):
        await _press(hass, f"button.{prefix}_refresh")
    assert hass.states.get(f"sensor.{prefix}_first_stops").state == "3"
    q = hass.states.get(f"binary_sensor.{prefix}_api_quota")
    assert q.state == "on" and q.attributes["초과된 API"] == ["버스위치 (busposinfo)"]

    # 위치는 되는데 도착정보만 한도 초과: 정류장 수는 보이고 도착예정시간은 없음
    with (
        patch.object(DaejeonBusApi, "get_bus_positions", return_value=POSITIONS),
        patch.object(DaejeonBusApi, "get_arrivals", side_effect=quota("arrive")),
    ):
        await _press(hass, f"button.{prefix}_refresh")
    assert hass.states.get(f"sensor.{prefix}_first_stops").state == "3"
    assert hass.states.get(f"sensor.{prefix}_first_minutes").state == "unknown"
    q = hass.states.get(f"binary_sensor.{prefix}_api_quota")
    assert q.attributes["초과된 API"] == ["도착정보 (arrive)"]
