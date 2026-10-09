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


def busy_from(events: list[Event], plan: list[PlanItem] | None = None) -> list[tuple[datetime, datetime]]:
    busy = [(e.start, e.end) for e in events]
    busy += [(p.start, p.end) for p in plan or []]
    return busy
