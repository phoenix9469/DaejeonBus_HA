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

정류소 하나당 항목 하나를 추가합니다. API 키·이름·대상 버스는 나중에 `구성`에서 바꿀 수 있습니다.

## 엔티티 (arsId `31770` 예시)

| 엔티티 | 상태 | 주요 속성 |
| --- | --- | --- |
| `button.daejeon_bus_31770_refresh` | 새로고침 버튼 | – |
| `sensor.daejeon_bus_31770` | 도착예정 버스 수 | `버스 목록` (노선별 첫 차 요약) |
| `sensor.daejeon_bus_31770_3` (노선별) | 도착예정시간, 예: `1분 48초` | `잔여 정류장 수`, `최근 통과 정류소`, `도착예정시간`, `도착예정(분)`, `도착예정(초)`, `행선지`, `차량번호`, `정보 제공 시각`, `다음 버스` |
| `sensor.daejeon_bus_31770_last_update` | 마지막 조회 시각 | – |

- 노선 센서는 도착정보에 나타난 노선마다 생성되며, 새로고침 후 새 노선이 보이면 자동으로 추가됩니다.
- 해당 노선의 도착정보가 없으면 상태는 `도착정보 없음`입니다.
- `최근 통과 정류소`는 API가 주는 정류소 ID(`LAST_STOP_ID`)입니다.

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
      | {{ b['노선'] }} | {{ b['도착예정시간'] }} | {{ b['잔여 정류장 수'] }} | {{ b['최근 통과 정류소'] }} | {{ b['행선지'] }} |
      {% endfor %}
```

자동화에서 조회하려면 `button.press` 서비스로 새로고침 버튼을 누르면 됩니다.

> 참고: API의 `EXTIME_SEC`는 전체 남은 초, `EXTIME_MIN`은 올림한 분입니다. 상태값(`5분 7초` 등)은 `EXTIME_SEC` 기준입니다.
