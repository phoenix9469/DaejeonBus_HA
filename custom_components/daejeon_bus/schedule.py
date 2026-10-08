"""자동 조회 시간대 판정."""
from __future__ import annotations

from datetime import datetime, time

from .const import WEEKDAYS


def parse_time(value: str | None, default: time) -> time:
    """'HH:MM' 또는 'HH:MM:SS' 문자열."""
    if not value:
        return default
    try:
        parts = [int(p) for p in str(value).split(":")]
        return time(parts[0], parts[1] if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return default


def in_window(now: datetime, start: time, end: time, weekdays: list[str]) -> bool:
    """now가 요일/시간대 안인지. start == end 이면 하루 종일, 자정을 넘는 구간도 지원.

    자정을 넘는 구간(예: 23:00~01:00)은 시작한 날의 요일 기준이다.
    """
    current = now.time().replace(second=0, microsecond=0)
    day = WEEKDAYS[now.weekday()]
    prev_day = WEEKDAYS[(now.weekday() - 1) % 7]

    if start == end:
        return day in weekdays
    if start < end:
        return day in weekdays and start <= current <= end
    # 자정을 넘는 구간
    if current >= start:
        return day in weekdays
    if current <= end:
        return prev_day in weekdays
    return False
