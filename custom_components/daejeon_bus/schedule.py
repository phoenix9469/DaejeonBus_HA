"""자동 조회 시간대 판정."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .const import (
    CONF_AUTO_END,
    CONF_AUTO_INTERVAL,
    CONF_AUTO_REFRESH,
    CONF_AUTO_START,
    CONF_AUTO_WEEKDAYS,
    DEFAULT_AUTO_END,
    DEFAULT_AUTO_INTERVAL,
    DEFAULT_AUTO_START,
    DEFAULT_AUTO_WEEKDAYS,
    API_NAMES,
    DEV_DAILY_LIMIT,
    MIN_AUTO_INTERVAL,
    WEEKDAY_NAMES,
    WEEKDAYS,
)


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


def window_minutes(start: time, end: time) -> int:
    """하루 중 자동 조회 시간대 길이(분). start == end 이면 하루 종일."""
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute
    if s == e:
        return 24 * 60
    return e - s if e > s else 24 * 60 - s + e


def auto_interval(conf: dict[str, Any]) -> int:
    try:
        interval = int(float(conf.get(CONF_AUTO_INTERVAL, DEFAULT_AUTO_INTERVAL)))
    except (TypeError, ValueError):
        interval = DEFAULT_AUTO_INTERVAL
    return max(interval, MIN_AUTO_INTERVAL)


def estimate_auto_calls(
    conf: dict[str, Any],
    per_refresh: dict[str, int],
    per_day_extra: dict[str, int] | None = None,
) -> dict[str, Any]:
    """자동 조회 설정으로 예상되는 API 호출 수.

    per_refresh: 1회 조회당 API(서비스)별 호출 수
    per_day_extra: 조회하는 날 하루 1번 더 부르는 API (예: 노선 정류장 목록)
    """
    enabled = bool(conf.get(CONF_AUTO_REFRESH, False))
    weekdays = [d for d in WEEKDAYS if d in conf.get(CONF_AUTO_WEEKDAYS, DEFAULT_AUTO_WEEKDAYS)]
    interval = auto_interval(conf)
    minutes = window_minutes(
        parse_time(conf.get(CONF_AUTO_START), parse_time(DEFAULT_AUTO_START, time(7))),
        parse_time(conf.get(CONF_AUTO_END), parse_time(DEFAULT_AUTO_END, time(9))),
    )
    refreshes = (minutes * 60) // interval + (0 if minutes == 24 * 60 else 1)
    if not enabled or not weekdays:
        refreshes = 0

    per_day = {api: n * refreshes for api, n in per_refresh.items()}
    if refreshes:
        for api, n in (per_day_extra or {}).items():
            per_day[api] = per_day.get(api, 0) + n
    busiest = max(per_day.values(), default=0)
    return {
        "enabled": enabled and bool(weekdays),
        "interval": interval,
        "window_minutes": minutes,
        "weekdays": weekdays,
        "refreshes_per_day": refreshes,
        "per_day": per_day,
        "total_per_day": sum(per_day.values()),
        "total_per_week": sum(per_day.values()) * len(weekdays),
        "busiest_percent": round(busiest / DEV_DAILY_LIMIT * 100, 1),
    }


def format_estimate(est: dict[str, Any]) -> str:
    """옵션 확인 화면에 보여줄 예상 호출 수 요약 (마크다운)."""
    if not est["enabled"]:
        return "자동 조회가 꺼져 있습니다. 새로고침 버튼을 누를 때만 API를 호출합니다."
    hours, mins = divmod(est["window_minutes"], 60)
    days = ", ".join(WEEKDAY_NAMES[d] for d in est["weekdays"])
    lines = [
        f"- 조회 시간대: 하루 {hours}시간 {mins}분 ({days})",
        f"- 간격: {est['interval']}초 → 하루 약 **{est['refreshes_per_day']:,}회** 조회",
        "",
        "| API | 하루 예상 | 개발계정 한도 대비 |",
        "| --- | --- | --- |",
    ]
    for api, n in est["per_day"].items():
        pct = n / DEV_DAILY_LIMIT * 100
        warn = " ⚠️" if n > DEV_DAILY_LIMIT else ""
        lines.append(f"| {API_NAMES.get(api, api)} | {n:,}회 | {pct:.0f}%{warn} |")
    lines += [
        "",
        f"하루 합계 **{est['total_per_day']:,}회**, 주간 합계 **{est['total_per_week']:,}회**",
    ]
    if any(n > DEV_DAILY_LIMIT for n in est["per_day"].values()):
        lines.append("")
        lines.append(
            f"⚠️ 개발계정 일일 한도({DEV_DAILY_LIMIT:,}회)를 넘습니다. 간격을 늘리거나 시간대를 줄이세요."
        )
    return "\n".join(lines)
