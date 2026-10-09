"""Non-LLM baseline planner. Used as fallback and as the eval baseline."""

from datetime import date, timedelta

from .models import PRIORITY_RANK, Event, Issue, PlanItem
from .scheduling import DEFAULT_BLOCK, busy_from, free_gaps

BLOCK = DEFAULT_BLOCK


def _score(i: Issue, day: date) -> tuple:
    overdue = 0 if i.due and i.due <= day else 1
    return (overdue, PRIORITY_RANK.get(i.priority, 2), i.due or date.max, i.updated)


def heuristic_plan(issues: list[Issue], events: list[Event], day: date, limit: int = 5) -> list[PlanItem]:
    plan: list[PlanItem] = []
    for i in sorted(issues, key=lambda x: _score(x, day)):
        if len(plan) == limit:
            break
        gaps = free_gaps(day, busy_from(events, plan))
        slot = next((g for g in gaps if g[1] - g[0] >= timedelta(minutes=BLOCK)), None)
        if not slot:
            break
        why = f"prioridad {i.priority}" + (f", vence {i.due:%d/%m}" if i.due else "") + f", estado {i.status}"
        plan.append(PlanItem(i.key, why, slot[0], BLOCK))
    return plan
