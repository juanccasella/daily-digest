"""The report: Avanzó / Ayudó a objetivos / Sigue. Built from validated pieces; final critic here."""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date

from .models import Claim, Event, Goal, GoalLink, Issue, JiraChange, PlanItem
from .security import sanitize
from .validate import validate_claims, validate_links
from .window import Window


@dataclass
class Report:
    day: date
    window: Window
    offline: bool
    advanced: list[Claim]
    goal_links: list[GoalLink]
    goals: list[Goal]
    plan: list[PlanItem]
    issues: list[Issue]
    events_today: list[Event]
    warnings: list[str]
    provenance: dict
    attempts: dict
    known_ids: set[str]
    goals_source: str = ""
    carried: list[Claim] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def goal_ids(self) -> set[str]:
        return {g.id for g in self.goals}


def advanced_from_code(changes: list[JiraChange], events_window: list[Event]) -> list[Claim]:
    """What moved in Jira and which meetings happened: deterministic, no LLM needed."""
    out: list[Claim] = []
    by_key: "OrderedDict[str, list[JiraChange]]" = OrderedDict()
    for c in sorted(changes, key=lambda c: c.at):
        by_key.setdefault(c.key, []).append(c)
    for key, cs in by_key.items():
        summary = sanitize(cs[0].summary, 90)
        moves = [c.detail for c in cs if c.kind == "transition"]
        comments = sum(1 for c in cs if c.kind == "comment")
        parts = []
        if moves:
            parts.append("pasó " + "; ".join(moves))
        if comments:
            parts.append(f"{comments} comentario(s) nuevo(s)")
        out.append(Claim(f"{key} «{summary}»: {', '.join(parts)}.", (f"jira:{key}",)))
    for e in sorted(events_window, key=lambda e: e.start):
        out.append(Claim(f"Reunión «{sanitize(e.subject, 80)}» ({e.start:%d/%m %H:%M}-{e.end:%H:%M}).", (e.cite,)))
    return out


def known_ids(s: dict) -> set[str]:
    ids = {i.cite for i in s.get("issues", [])} | {c.cite for c in s.get("changes", [])}
    ids |= {e.cite for e in s.get("events_today", []) + s.get("events_window", [])}
    ids |= {m.cite for m in s.get("mails", []) + s.get("chats", [])}
    return ids | {g.id for g in s.get("goals", [])}


def finalize(s: dict, window: Window) -> Report:
    """Final gate: anything that still fails validation is dropped, and the report says so."""
    known = known_ids(s)
    goals = s.get("goals", [])
    goal_ids = {g.id for g in goals}
    warnings = list(dict.fromkeys(s.get("warnings", [])))

    reasons: list[str] = []

    def keep(errs: list[str]) -> bool:
        reasons.extend(errs)
        return not errs

    advanced = s.get("advanced", []) + s.get("reader_claims", [])
    kept_adv = [c for c in advanced if keep(validate_claims([c], known))]
    kept_links = [ln for ln in s.get("links", []) if keep(validate_links([ln], known - goal_ids, goal_ids))]
    plan = s.get("plan", [])
    kept_plan = [p for p in plan if keep(validate_claims([Claim(p.reason, (p.cite,))], known))]
    kept_carried = [c for c in s.get("carried", []) if keep(validate_claims([c], known))]
    dropped = (len(advanced) - len(kept_adv)) + (len(s.get("links", [])) - len(kept_links)) + (len(plan) - len(kept_plan))
    if dropped:
        warnings.append(f"validador final: se descartaron {dropped} afirmación(es) inválidas. Motivos: "
                        + " | ".join(sanitize(r, 120) for r in reasons[:3]))

    report = Report(
        day=s["day"], window=window, offline=bool(s.get("offline")), advanced=kept_adv, goal_links=kept_links,
        goals=goals, plan=kept_plan, issues=s.get("issues", []), events_today=s.get("events_today", []),
        warnings=warnings, provenance=dict(s.get("provenance", {})), attempts=dict(s.get("attempts", {})),
        known_ids=known, goals_source=s.get("goals_source", ""), carried=kept_carried,
        done=list(s.get("done", [])),
    )
    from .validate import validate_report

    report.errors = validate_report(report)
    return report
