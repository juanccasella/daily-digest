"""The "yesterday" window: by default the previous working day (Monday looks at Friday)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


def previous_workday(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d


@dataclass(frozen=True)
class Window:
    start: date  # inclusive
    end: date  # inclusive

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError(f"Ventana inválida: {self.start} > {self.end}")

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min)

    @property
    def end_dt(self) -> datetime:
        """Exclusive upper bound."""
        return datetime.combine(self.end + timedelta(days=1), time.min)

    def contains(self, at: datetime) -> bool:
        return self.start_dt <= at < self.end_dt

    def label(self) -> str:
        if self.start == self.end:
            return f"{self.start:%d/%m/%Y}"
        return f"{self.start:%d/%m/%Y} al {self.end:%d/%m/%Y}"


def resolve(day: date, since: date | None = None, until: date | None = None) -> Window:
    if since is None and until is None:
        d = previous_workday(day)
        return Window(d, d)
    since = since or until
    until = until or since
    return Window(since, until)
