"""테스트 공용: 노선 경유 정류장 API(getStaionByRoute) 가짜 응답."""

# 노선 ID -> {정류장 arsId: 이름} (fixture_31770.xml의 3번/103번/116번 노선)
ROUTE_STOP_NAMES = {
    "30300104": {"31910": "갈마육교", "31770": "갈마네거리"},
    "30300038": {"31350": "KT인재개발원", "31770": "갈마네거리"},
    "30300048": {"99999": "새정류소", "31770": "갈마네거리"},
}


def fake_route_stops(route_cd: str) -> list[dict[str, str]]:
    stops = ROUTE_STOP_NAMES.get(route_cd, {})
    return [
        {"BUSSTOP_SEQ": str(i + 1), "BUS_STOP_ID": ars, "BUSSTOP_NM": name,
         "TOTAL_DIST": str((i + 1) * 300), "ROUTE_CD": route_cd}
        for i, (ars, name) in enumerate(stops.items())
    ]
