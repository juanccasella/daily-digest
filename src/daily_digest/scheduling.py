"""Pure scheduling helpers: working window, overlaps, free gaps. No I/O, no LLM."""

from datetime import date, datetime, time, timedelta

from .models import Event, PlanItem

WORK_START = time(9, 0)
WORK_END = time(18, 0)
MIN_BLOCK, MAX_BLOCK = 15, 180
DEFAULT_BLOCK = 60  # heuristic block size; also the minimum gap for which an empty plan is rejected


def window(day: date) -> tuple[datetime, datetime]:
    return datetime.combine(day, WORK_START), datetime.combine(day, WORK_END)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def free_gaps(day: date, busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    cursor, end = window(day)
    gaps = []
    for s, e in sorted(busy):
        if s > cursor:
            gaps.append((cursor, min(s, end)))
        cursor = max(cursor, e)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return [(s, e) for s, e in gaps if e - s >= timedelta(minutes=MIN_BLOCK)]


def covers_workday(e: Event, day: date) -> bool:
    """An event spanning the whole working window (e.g. "Flock IT AI DAY 09-18", vacations, home office)
    is informative: it is shown, but does not block the plan. Set DIGEST_ALLDAY_BLOQUEA=1 to make it block."""
    ws, we = window(day)
    return e.start <= ws and e.end >= we


def blocking(events: list[Event], day: date) -> list[Event]:
    import os

    if os.getenv("DIGEST_ALLDAY_BLOQUEA") == "1":
        return list(events)
    return [e for e in events if not covers_workday(e, day)]


def busy_from(events: list[Event], plan: list[PlanItem] | None = None) -> list[tuple[datetime, datetime]]:
    busy = [(e.start, e.end) for e in events]
    busy += [(p.start, p.end) for p in plan or []]
    return busy
