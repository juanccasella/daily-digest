"""Memory between days: SQLite round trip and carry-over rules."""

from datetime import date, datetime

from daily_digest.memory import SqliteMemory, carried_over
from daily_digest.models import Issue, JiraChange, PlanItem
from daily_digest.window import Window

D8, D9 = date(2026, 10, 8), date(2026, 10, 9)


def _issue(key):
    return Issue(key, f"Ticket {key}", "To Do", "Medium", None, datetime(2026, 10, 1))


def test_sqlite_round_trip_and_replace(tmp_path):
    mem = SqliteMemory(tmp_path / "m.db")
    mem.save_plan(D8, [PlanItem("A-1", "r", datetime(2026, 10, 8, 10), 60)], "llm")
    mem.save_plan(D8, [PlanItem("A-2", "r", datetime(2026, 10, 8, 11), 60)], "llm")  # same day: replaces
    mem.save_plan(D9, [PlanItem("A-3", "r", datetime(2026, 10, 9, 10), 60)], "llm")
    assert mem.planned_in(Window(D8, D8)) == [(D8, "A-2")]
    assert [k for _, k in mem.planned_in(Window(D8, D9))] == ["A-2", "A-3"]


def test_reason_is_sanitized_before_storing(tmp_path):
    mem = SqliteMemory(tmp_path / "m.db")
    mem.save_plan(D8, [PlanItem("A-1", "ver https://x.invalid <b>ya</b>", datetime(2026, 10, 8, 10), 60)], "llm")
    (reason,) = mem.conn.execute("SELECT reason FROM planned").fetchone()
    assert "http" not in reason and "<b>" not in reason


def test_carried_over_only_open_and_unmoved():
    planned = [(D8, "A-1"), (D8, "A-2"), (D8, "A-3"), (D8, "A-1")]
    issues = [_issue("A-1"), _issue("A-2")]  # A-3 closed
    changes = [JiraChange("A-2", "x", datetime(2026, 10, 8, 12), "transition", "To Do → Done")]
    out = carried_over(planned, issues, changes)
    assert [c.cites for c in out] == [("jira:A-1",)]  # A-2 moved, A-3 closed, duplicate A-1 once
