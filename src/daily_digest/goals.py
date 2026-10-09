"""Goals file: `_local-only/goals.md` (real, never in git) or `fixtures/goals.md` (fictional).

Format: one goal per bullet. `- [goal:2] text` keeps an explicit id; plain `- text` bullets are
numbered in order. Blockquotes and headings are ignored.
"""

import re
from pathlib import Path

from .models import Goal

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "_local-only" / "goals.md"
FIXTURE = ROOT / "fixtures" / "goals.md"

_BULLET = re.compile(r"^\s*[-*]\s+(?:\[(goal:\d+)\]\s*)?(.+?)\s*$")


def parse(text: str) -> list[Goal]:
    goals: list[Goal] = []
    used: set[str] = set()
    pending: list[str] = []
    for line in text.splitlines():
        m = _BULLET.match(line)
        if not m:
            continue
        gid, body = m.group(1), m.group(2).strip()
        if gid:
            if gid in used:
                raise ValueError(f"Objetivo duplicado: {gid}")
            used.add(gid)
            goals.append(Goal(gid, body))
        else:
            pending.append(body)
    n = 1
    for body in pending:
        while f"goal:{n}" in used:
            n += 1
        used.add(f"goal:{n}")
        goals.append(Goal(f"goal:{n}", body))
    return goals


def load(local: Path = LOCAL, fixture: Path = FIXTURE, offline: bool = False) -> tuple[list[Goal], str]:
    """Offline runs always use the fictional fixture so demos never show real goals."""
    path = fixture if offline or not local.exists() else local
    if not path.exists():
        return [], "sin archivo de objetivos"
    return parse(path.read_text(encoding="utf-8")), path.name if path == fixture else "_local-only/goals.md"
