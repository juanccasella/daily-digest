"""Structured view of a report for the web planner (same validated content as the Markdown).

Every text here is already sanitized by the pipeline; the UI must still render it as text
(textContent), never as HTML, because part of it comes from third-party mails and chats.
"""

from .render import goal_title, group_by_goal
from .report import Report
from .scheduling import blocking
from .security import sanitize


def _item(c) -> dict:
    return {"text": sanitize(c.text, 400), "cites": list(c.cites)}


def report_json(r: Report) -> dict:
    busy = {e.cite for e in blocking(r.events_today, r.day)}
    plan = {p.key: p for p in r.plan}
    carried = {c.cites[0].removeprefix("jira:") for c in r.carried}
    done = set(r.done)
    tasks = []
    for i in r.issues:
        p = plan.get(i.key)
        related = [_item(c) for c in r.advanced if f"jira:{i.key}" in c.cites]
        tasks.append({
            "key": i.key, "cite": i.cite, "summary": sanitize(i.summary, 200), "status": i.status,
            "priority": i.priority, "due": i.due.isoformat() if i.due else None,
            "updated": i.updated.date().isoformat(), "url": i.url,
            "done": i.key in done, "carried": i.key in carried,
            "planned": {"start": f"{p.start:%H:%M}", "end": f"{p.end:%H:%M}", "reason": sanitize(p.reason, 300)} if p else None,
            "related": related,
            "goals": [ln.goal for ln in r.goal_links if i.cite in ln.cites],
        })
    order = lambda t: (t["done"], t["planned"] is None, t["planned"]["start"] if t["planned"] else "", not t["carried"])  # noqa: E731
    return {
        "day": r.day.isoformat(), "window": r.window.label(), "offline": r.offline, "errors": list(r.errors),
        "warnings": [sanitize(w, 400) for w in r.warnings], "provenance": r.provenance,
        "goals": [{"id": g.id, "title": goal_title(g.text), "text": sanitize(g.text, 300),
                   "links": [_item(ln) for ln in r.goal_links if ln.goal == g.id]} for g in r.goals],
        "progress": [{"title": title, "items": [_item(c) for c in claims]} for title, claims in group_by_goal(r)],
        "carried": [_item(c) for c in r.carried],
        "meetings": [{"cite": e.cite, "subject": sanitize(e.subject, 120), "start": f"{e.start:%H:%M}",
                      "end": f"{e.end:%H:%M}", "all_day": e.cite not in busy}
                     for e in sorted(r.events_today, key=lambda e: e.start)],
        "tasks": sorted(tasks, key=order),
    }
