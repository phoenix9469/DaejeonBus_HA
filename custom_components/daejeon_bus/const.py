DOMAIN = "daejeon_bus"

VERSION = "1.0.0"
MANUFACTURER = "Daejeon Bus"

BASE_URL = "https://apis.data.go.kr/6300000"
ARRIVE_URL = f"{BASE_URL}/arrive/getArrInfoByUid"

CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_INCLUDE_BUSES = "include_buses"

# 도착정보 메시지 유형(MSG_TP)
MSG_TP_ENTERING = "06"  # 진입중
MSG_TP_WAITING = "07"  # 운행대기 (차고지 대기, 도착시간 의미 없음)

STATUS_ENTERING = "진입중"
STATUS_WAITING = "운행대기"
STATUS_RUNNING = "운행중"
