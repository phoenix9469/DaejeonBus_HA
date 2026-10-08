"""정류소 번호(arsId) -> 정류소 이름 변환표.

1. 사용자 CSV (설정의 '정류소 CSV 파일 경로')
2. 내장 목록 stops.json (국토교통부 전국 버스정류장 위치정보, 대전 2023-10 기준)
순으로 찾고, 둘 다 없으면 코디네이터가 정류소정보 API로 조회한다.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

BUNDLED_FILE = Path(__file__).parent / "stops.json"

# CSV 헤더 후보 (앞쪽이 우선)
ID_COLUMNS = (
    "모바일단축번호",  # 국토교통부 전국 버스정류장 위치정보
    "BUS_STOP_ID",  # 대전 BIS 노선별 경유 정류소
    "ARO_BUSSTOP_ID",  # 대전 BIS 정류소정보
    "arsId",
    "ARS_ID",
    "ARS번호",
    "정류소번호",
    "정류장번호",
)
NAME_COLUMNS = ("정류장명", "정류소명", "BUSSTOP_NM", "STOP_NAME", "정류소명칭", "name")
CITY_CODE_COLUMN = "도시코드"
DAEJEON_CITY_CODE = "25"


def load_bundled() -> dict[str, str]:
    try:
        return json.loads(BUNDLED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("내장 정류소 목록을 읽지 못했습니다: %s", err)
        return {}


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _pick(header: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {h.strip().lower(): h for h in header}
    for cand in candidates:
        if cand.lower() in normalized:
            return normalized[cand.lower()]
    return None


def parse_csv(text: str) -> dict[str, str]:
    """CSV 텍스트에서 arsId -> 이름 표를 만든다. 열 이름은 자동 인식."""
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    id_col = _pick(header, ID_COLUMNS)
    name_col = _pick(header, NAME_COLUMNS)
    if not id_col or not name_col:
        raise ValueError(
            f"정류소 번호/이름 열을 찾지 못했습니다. 헤더: {header}. "
            f"번호 열 후보: {ID_COLUMNS}, 이름 열 후보: {NAME_COLUMNS}"
        )
    city_col = CITY_CODE_COLUMN if CITY_CODE_COLUMN in header else None

    stops: dict[str, str] = {}
    for row in reader:
        if city_col and str(row.get(city_col) or "").strip() != DAEJEON_CITY_CODE:
            continue
        ars_id = str(row.get(id_col) or "").strip()
        name = str(row.get(name_col) or "").strip()
        if ars_id and name:
            stops.setdefault(ars_id, name)
    return stops


def load_csv(path: str) -> dict[str, str]:
    """사용자 CSV 파일을 읽는다 (UTF-8 / CP949 자동 판별)."""
    return parse_csv(_decode(Path(path).read_bytes()))


def load_stop_names(csv_path: str | None) -> dict[str, str]:
    """내장 목록 위에 사용자 CSV를 덮어쓴 변환표."""
    stops = load_bundled()
    if csv_path:
        try:
            custom = load_csv(csv_path)
        except (OSError, ValueError) as err:
            _LOGGER.warning("정류소 CSV(%s)를 읽지 못했습니다: %s", csv_path, err)
        else:
            _LOGGER.debug("정류소 CSV에서 %d개 정류소를 읽었습니다", len(custom))
            stops.update(custom)
    return stops
