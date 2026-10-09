"""Memory between days: which tickets were planned for which day.

Stored as structured facts (day, ticket, block, reason), never raw text from mails or chats.
Real runs use SQLite in `_local-only/digest.db` (gitignored); offline demos and evals use an
in-memory store seeded from fixtures so they never touch the real database.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .models import Claim, Issue, JiraChange, PlanItem
from .security import sanitize
from .window import Window

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "_local-only" / "digest.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS planned (
    day      TEXT NOT NULL,   -- ISO date the block was planned for
    key      TEXT NOT NULL,   -- Jira key
    start    TEXT NOT NULL,   -- HH:MM
    minutes  INTEGER NOT NULL,
    reason   TEXT NOT NULL,
    source   TEXT NOT NULL,   -- llm | llm-after-retry | heuristic | heuristic-fallback
    saved_at TEXT NOT NULL,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS task_status (
    key    TEXT PRIMARY KEY,  -- Jira key; latest status wins
    status TEXT NOT NULL,     -- done | open
    day    TEXT NOT NULL,     -- day it was marked
    at     TEXT NOT NULL
);
"""
STATUSES = ("done", "open")


class Memory(Protocol):
    def planned_in(self, w: Window) -> list[tuple[date, str]]: ...
    def save_plan(self, day: date, plan: list[PlanItem], source: str) -> None: ...
    def done_keys(self) -> set[str]: ...
    def set_status(self, day: date, key: str, status: str) -> None: ...


class SqliteMemory:
    def __init__(self, path: Path | str = DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def planned_in(self, w: Window) -> list[tuple[date, str]]:
        rows = self.conn.execute("SELECT day, key FROM planned WHERE day BETWEEN ? AND ? ORDER BY day, start",
                                 (w.start.isoformat(), w.end.isoformat())).fetchall()
        return [(date.fromisoformat(d), k) for d, k in rows]

    def save_plan(self, day: date, plan: list[PlanItem], source: str) -> None:
        """Re-running the same day replaces that day's plan (the latest plan is the one that counts)."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            self.conn.execute("DELETE FROM planned WHERE day = ?", (day.isoformat(),))
            self.conn.executemany(
                "INSERT INTO planned VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(day.isoformat(), p.key, f"{p.start:%H:%M}", p.minutes, sanitize(p.reason, 300), source, now) for p in plan])

    def done_keys(self) -> set[str]:
        return {k for (k,) in self.conn.execute("SELECT key FROM task_status WHERE status = 'done'")}

    def set_status(self, day: date, key: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"estado inválido: {status}")
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO task_status VALUES (?, ?, ?, ?)",
                              (key, status, day.isoformat(), datetime.now().isoformat(timespec="seconds")))


class StaticMemory:
    """Fixture/eval memory: `[{"key": "DEMO-08"}]` means "planned for the window start"."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.saved: list[tuple[date, list[PlanItem], str]] = []

    def planned_in(self, w: Window) -> list[tuple[date, str]]:
        return [(date.fromisoformat(r["day"]) if r.get("day") else w.start, r["key"]) for r in self.rows if "status" not in r]

    def save_plan(self, day: date, plan: list[PlanItem], source: str) -> None:
        self.saved.append((day, plan, source))

    def done_keys(self) -> set[str]:
        return {r["key"] for r in self.rows if r.get("status") == "done"}

    def set_status(self, day: date, key: str, status: str) -> None:
        self.rows = [r for r in self.rows if not (r["key"] == key and "status" in r)] + [{"key": key, "status": status}]


def carried_over(planned: list[tuple[date, str]], issues: list[Issue], changes: list[JiraChange],
                 done: set[str] | None = None) -> list[Claim]:
    """Planned in the window, still open, nothing moved in Jira and not marked done → carried over."""
    open_ = {i.key: i for i in issues if i.key not in (done or set())}
    moved = {c.key for c in changes}
    out, seen = [], set()
    for day, key in planned:
        if key in open_ and key not in moved and key not in seen:
            seen.add(key)
            out.append(Claim(f"{key} «{sanitize(open_[key].summary, 80)}»: lo planificaste para el {day:%d/%m} "
                             "y no tuvo movimiento en Jira.", (f"jira:{key}",)))
    return out
