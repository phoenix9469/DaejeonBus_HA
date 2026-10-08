DOMAIN = "daejeon_bus"

VERSION = "1.0.0"
MANUFACTURER = "Daejeon Bus"

BASE_URL = "https://apis.data.go.kr/6300000"
ARRIVE_URL = f"{BASE_URL}/arrive/getArrInfoByUid"
BUS_POS_URL = f"{BASE_URL}/busposinfo/getBusPosByRtid"
ROUTE_STOPS_URL = f"{BASE_URL}/busRouteInfo/getStaionByRoute"
# 정류소정보 조회(getStationByUid). 공공데이터포털 경로를 먼저 시도하고,
# 실패하면 대전시 BIS 원본 서버(활용가이드 v1.3 기준)를 시도한다.
STATION_URLS = (
    f"{BASE_URL}/stationinfo/getStationByUid",
    "http://openapitraffic.daejeon.go.kr/api/rest/stationinfo/getStationByUid",
)

# 항목 유형
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_STATION = "station"  # 정류소 도착정보
ENTRY_TYPE_COMMUTE = "commute"  # 노선으로 조회 (노선 + 내 정류장)

CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_INCLUDE_BUSES = "include_buses"
CONF_SOON_MINUTES = "soon_minutes"

DEFAULT_SOON_MINUTES = 3

# 노선으로 조회
CONF_ROUTE_CD = "route_cd"
CONF_ROUTE_NO = "route_no"
CONF_STOP_SEQ = "stop_seq"
CONF_WALK_MINUTES = "walk_minutes"
CONF_LEAVE_MARGIN = "leave_margin"

DEFAULT_WALK_MINUTES = 5
DEFAULT_LEAVE_MARGIN = 1
# 도착정보로 속도를 보정할 수 없을 때 쓰는 기본 버스 속도 (정차 포함 약 15km/h)
DEFAULT_BUS_METERS_PER_MINUTE = 250
ROUTE_STOPS_MAX_AGE_HOURS = 24

# 자동 조회 (기본 꺼짐)
CONF_AUTO_REFRESH = "auto_refresh"
CONF_AUTO_START = "auto_start"
CONF_AUTO_END = "auto_end"
CONF_AUTO_WEEKDAYS = "auto_weekdays"
CONF_AUTO_INTERVAL = "auto_interval"

DEFAULT_AUTO_START = "07:00:00"
DEFAULT_AUTO_END = "09:00:00"
DEFAULT_AUTO_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
DEFAULT_AUTO_INTERVAL = 60
MIN_AUTO_INTERVAL = 30
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# ---- 활용가이드(OpenAPI 활용가이드 v1.3) 코드표 ----

# MSG_TP 메시지유형
MSG_TP_ARRIVED = "01"
MSG_TP_DEPARTED = "02"
MSG_TP_SOON = "03"
MSG_TP_CROSSING = "04"
MSG_TP_ENTERING = "06"
MSG_TP_WAITING = "07"
MSG_TP_NAMES = {
    MSG_TP_ARRIVED: "도착",
    MSG_TP_DEPARTED: "출발",
    MSG_TP_SOON: "몇분후 도착",
    MSG_TP_CROSSING: "교차로 통과",
    MSG_TP_ENTERING: "진입중",
    MSG_TP_WAITING: "차고지 운행대기중",
}

STATUS_ARRIVED = "도착"
STATUS_ENTERING = "진입중"
STATUS_SOON = "곧 도착"
STATUS_WAITING = "운행대기"
STATUS_RUNNING = "운행중"

# LAST_CAT 첫/막차 구분
LAST_CAT_NAMES = {"1": "첫차", "2": "막차", "3": "일반"}

# ROUTE_TP 노선유형
ROUTE_TP_NAMES = {
    "1": "급행",
    "2": "간선",
    "3": "지선",
    "4": "외곽",
    "5": "마을",
    "6": "첨단",
}
