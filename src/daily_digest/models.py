"""Domain objects. Every source item exposes a stable, citable id (`cite`)."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

PRIORITY_RANK = {"Highest": 0, "High": 1, "Medium": 2, "Low": 3, "Lowest": 4}
CITE_PREFIXES = ("jira", "cal", "mail", "chat", "goal")


def short_id(raw: str) -> str:
    """Stable 8-hex id derived from a source id (Graph ids are long and opaque)."""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str
    status: str
    priority: str
    due: date | None
    updated: datetime
    url: str = ""

    @property
    def cite(self) -> str:
        return f"jira:{self.key}"


@dataclass(frozen=True)
class Event:
    subject: str
    start: datetime  # naive, local time
    end: datetime
    uid: str = ""

    @property
    def cite(self) -> str:
        return f"cal:{short_id(self.uid or f'{self.subject}|{self.start:%Y-%m-%dT%H:%M}')}"


@dataclass(frozen=True)
class JiraChange:
    """Something that moved in Jira inside the window: a status transition or a new comment."""

    key: str
    summary: str
    at: datetime  # naive, local time
    kind: str  # "transition" | "comment"
    detail: str  # "In Progress → Done" for transitions; never the comment body (untrusted)
    author: str = ""

    @property
    def cite(self) -> str:
        return f"jira:{self.key}"


@dataclass(frozen=True)
class Message:
    """A mail or a Teams chat message. Its text is UNTRUSTED input."""

    uid: str
    channel: str  # "mail" | "chat"
    sender: str
    subject: str  # mail subject or chat name
    sent: datetime  # naive, local time
    preview: str

    @property
    def cite(self) -> str:
        return f"{self.channel}:{short_id(self.uid)}"


@dataclass(frozen=True)
class Goal:
    id: str  # "goal:1"
    text: str


@dataclass(frozen=True)
class Claim:
    """One statement of the report. Must cite at least one real id."""

    text: str
    cites: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GoalLink:
    goal: str  # "goal:N"
    text: str
    cites: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlanItem:
    key: str
    reason: str
    start: datetime
    minutes: int

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)

    @property
    def cite(self) -> str:
        return f"jira:{self.key}"
