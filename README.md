# 대전 버스 (Daejeon Bus) for Home Assistant

대전광역시 버스정보(BIS) 공공데이터 API로 **정류소의 버스 도착정보**를 조회하는 Home Assistant 커스텀 통합구성요소입니다.
[miumida/seoul_bus](https://github.com/miumida/seoul_bus)를 참고해 만들었습니다.

- 입력: 정류소 번호 `arsId` (정류소 표지판의 5자리 번호, 예: `31770`)
- 출력: 노선별 **잔여 정류장 수**, **최근 통과 정류소**, **도착예정시간(분/초)**
- **자동 갱신 없음** — 통합구성요소 로드 시 1회 조회하고, 이후에는 `새로고침` 버튼을 누를 때만 조회합니다.

## 설치

### HACS
1. HACS → 사용자 지정 저장소 → `https://github.com/phoenix9469/DaejeonBus_HA` (유형: Integration)
2. `대전 버스` 설치 후 Home Assistant 재시작

### 수동
`custom_components/daejeon_bus` 폴더를 Home Assistant 설정 폴더의 `custom_components/` 아래에 복사한 뒤 재시작합니다.

## 설정
설정 → 기기 및 서비스 → 통합구성요소 추가 → **대전 버스**

| 항목 | 설명 |
| --- | --- |
| API 키 | [공공데이터포털](https://www.data.go.kr) 대전광역시 버스도착정보 서비스키 (인코딩/디코딩 키 모두 가능) |
| 정류소 번호 (arsId) | 예: `31770` |
| 정류소 이름 (선택) | 비워두면 API의 정류소 이름(`STOP_NAME`) 사용 |
| 대상 버스 목록 (선택) | 쉼표로 구분한 노선번호, 예: `3,103,119`. 비워두면 전체 노선 |
| 정류소 CSV 파일 경로 (선택) | 최근 통과 정류소 이름 변환용 CSV, 예: `/config/daejeon_bus_stops.csv` ([아래](#정류소-이름-변환) 참고) |

정류소 하나당 항목 하나를 추가합니다. API 키·이름·대상 버스·CSV 경로는 나중에 `구성`에서 바꿀 수 있습니다.

## 엔티티 (arsId `31770` 예시)

| 엔티티 | 상태 | 주요 속성 |
| --- | --- | --- |
| `button.daejeon_bus_31770_refresh` | 새로고침 버튼 | – |
| `sensor.daejeon_bus_31770` | 도착예정 버스 수 (운행대기 제외) | `버스 목록` (노선별 첫 차 요약) |
| `sensor.daejeon_bus_31770_3` (노선별) | `5분 7초` / `도착` / `진입중` / `운행대기` | `운행 상태`, `메시지 유형`, `첫/막차`, `노선유형`, `잔여 정류장 수`, `최근 통과 정류소`, `최근 통과 정류소 ID`, `도착예정시간`, `도착예정(분)`, `도착예정(초)`, `행선지`, `차량번호`, `정보 제공 시각`, `다음 버스` |
| `sensor.daejeon_bus_31770_last_update` | 마지막 조회 시각 | – |

- 노선 센서는 도착정보에 나타난 노선마다 생성되며, 새로고침 후 새 노선이 보이면 자동으로 추가됩니다.
- 해당 노선의 도착정보가 없으면 상태는 `도착정보 없음`입니다.
- `MSG_TP`에 따라 상태가 달라집니다: `01` → **도착**, `06` → **진입중**, `07` → **운행대기**(차고지 대기, 도착시간·위치 값 없음), 그 외 → 도착예정시간. 운행대기 버스는 목록 맨 뒤로 정렬됩니다.

## 도착정보 항목 (getArrInfoByUid)

대전 BIS「OpenAPI 활용가이드 v1.3」 기준입니다.

| 항목 | 뜻 | 값 / 비고 | 센서 속성 |
| --- | --- | --- | --- |
| `BUS_NODE_ID` | 요청 정류소 ID (7자리) | 예: `8001056` | – |
| `BUS_STOP_ID` | 요청 정류소 ARS-ID | 대전 5자리, 광역 6자리 | `정류소 ID(arsId)` |
| `STOP_NAME` | 요청 정류소 명칭 | | `정류소 이름` |
| `ROUTE_CD` | 노선 ID (8자리) | | `노선 ID` |
| `ROUTE_NO` | 노선번호 | | `노선번호` |
| `ROUTE_TP` | 노선유형 | 1 급행 · 2 간선 · 3 지선 · 4 외곽 · 5 마을 · 6 첨단 | `노선유형` |
| `DESTINATION` | 종점 | | `행선지` |
| `CAR_REG_NO` | 차량번호 | | `차량번호` |
| `EXTIME_MIN` | 도착예정시간(분) | 올림한 분 | `도착예정(분)` |
| `EXTIME_SEC` | 도착예정시간(초) | 남은 전체 초 (예: 317초 = 5분 17초, MIN=6) | `도착예정(초)`, `도착예정시간`, 상태값 |
| `STATUS_POS` | 잔여 정류장 수 | | `잔여 정류장 수` |
| `LAST_STOP_ID` | 최근 통과 정류소 ID (5자리 arsId) | 이름으로 변환 | `최근 통과 정류소`, `최근 통과 정류소 ID` |
| `MSG_TP` | 메시지유형 | 01 도착 · 02 출발 · 03 몇분후 도착 · 04 교차로 통과 · 06 진입중 · 07 차고지 운행대기중 | `메시지 유형`, `운행 상태` |
| `LAST_CAT` | 첫/막차 구분 | 1 첫차 · 2 막차 · 3 일반 (운행대기 차량은 0으로 오기도 함) | `첫/막차` |
| `INFO_OFFER_TM` | 정보 생성 시간 | | `정보 제공 시각` |

## 정류소 이름 변환

API는 최근 통과 정류소를 번호(`LAST_STOP_ID`)로만 줍니다. 이 번호를 이름으로 바꿀 때 아래 순서로 찾습니다.

1. **사용자 CSV** (설정의 `정류소 CSV 파일 경로`). 내장 목록보다 우선합니다.
2. **내장 목록** `stops.json`: 국토교통부 전국 버스정류장 위치정보 중 대전 2,902곳 (2023-10 기준)
3. **정류소정보 API** `stationinfo/getStationByUid?arsId=...`의 `BUSSTOP_NM`.
   - `https://apis.data.go.kr/6300000/stationinfo/getStationByUid`를 먼저 시도합니다. 실패하면 대전시 BIS 원본 서버 `http://openapitraffic.daejeon.go.kr/api/rest/stationinfo/getStationByUid`를 시도합니다.
   - 공공데이터포털에서 **대전광역시 정류소정보 조회 서비스**를 따로 활용신청해야 할 수 있습니다.
   - 한 번 찾은 이름은 기억해 두고, 실패한 번호는 다시 조회하지 않습니다. 모든 조회가 실패하면 HA를 재시작할 때까지 API 조회를 멈추고 번호를 그대로 보여줍니다.

### CSV 형식

열 이름을 자동으로 인식합니다(공백 무시). 인코딩은 UTF-8과 CP949(엑셀 기본), 구분자는 쉼표와 탭 모두 됩니다. 아래 형식을 그대로 쓸 수 있습니다.

- **대전광역시 시내버스 정류장 현황**: `관리번호`(= arsId), `정류장 이름` 열을 씁니다. 나머지 열(시군구명, 읍면동명, 지번 등)은 무시합니다.

- **국토교통부 전국 버스정류장 위치정보** ([공공데이터포털](https://www.data.go.kr/data/15067528/fileData.do)): `모바일단축번호`, `정류장명`, `도시코드` 열을 씁니다. `도시코드`가 있으면 대전(`25`) 행만 읽습니다.
- **대전 BIS 정류소/경유정류소 응답을 CSV로 저장한 것**: `BUS_STOP_ID` 또는 `ARO_BUSSTOP_ID`와 `BUSSTOP_NM` 열을 씁니다.

직접 만들 때는 이렇게 쓰면 됩니다.

```csv
arsId,정류소명
31910,갈마육교
31770,갈마네거리
```

파일은 Home Assistant 설정 폴더에 두고 `/config/daejeon_bus_stops.csv`처럼 절대경로로 지정합니다.

## 대시보드 예시

```yaml
type: vertical-stack
cards:
  - type: button
    entity: button.daejeon_bus_31770_refresh
    name: 새로고침
    tap_action:
      action: perform-action
      perform_action: button.press
      target:
        entity_id: button.daejeon_bus_31770_refresh
  - type: markdown
    content: >
      {% set s = 'sensor.daejeon_bus_31770' %}
      **{{ state_attr(s, '정류소 이름') }}** ({{ state_attr(s, '정류소 ID(arsId)') }})
      · 조회 {{ as_timestamp(states('sensor.daejeon_bus_31770_last_update')) | timestamp_custom('%H:%M:%S') }}

      | 노선 | 도착예정 | 남은 정류장 | 최근 통과 | 행선지 |
      |---|---|---|---|---|
      {% for b in state_attr(s, '버스 목록') or [] -%}
      | {{ b['노선'] }} | {{ b['도착예정'] }} | {{ b['잔여 정류장 수'] }} | {{ b['최근 통과 정류소'] }} | {{ b['행선지'] }} |
      {% endfor %}
```

자동화에서 조회하려면 `button.press` 서비스로 새로고침 버튼을 누르면 됩니다.

> 참고: API의 `EXTIME_SEC`는 전체 남은 초, `EXTIME_MIN`은 올림한 분입니다. 상태값(`5분 7초` 등)은 `EXTIME_SEC` 기준입니다.
