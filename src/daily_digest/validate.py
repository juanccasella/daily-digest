"""Deterministic critic: checks every claim against the real source data.

The LLM proposes; this module decides. Errors are fed back to the agent as feedback.
"""

import re
from datetime import date, timedelta

from .models import CITE_PREFIXES, Claim, Event, GoalLink, Issue, PlanItem
from .scheduling import DEFAULT_BLOCK, MAX_BLOCK, MIN_BLOCK, busy_from, free_gaps, overlaps, window
from .security import has_url

CITE_TOKEN = re.compile(r"\b(?:" + "|".join(CITE_PREFIXES) + r"):[A-Za-z0-9][A-Za-z0-9_-]*")
MAX_CLAIM_CHARS = 400


def validate(plan: list[PlanItem], issues: list[Issue], events: list[Event], day: date) -> list[str]:
    """Schedule critic for the planner ("Sigue" section)."""
    errors: list[str] = []
    known = {i.key for i in issues}
    ws, we = window(day)
    seen: set[str] = set()

    for p in plan:
        if p.key not in known:
            errors.append(f"{p.key}: no existe en Jira (inventada).")
        if p.key in seen:
            errors.append(f"{p.key}: duplicada en el plan.")
        seen.add(p.key)
        if not p.reason.strip():
            errors.append(f"{p.key}: falta el porqué (evidencia).")
        if has_url(p.reason):
            errors.append(f"{p.key}: el porqué contiene un enlace/URL (no permitido).")
        if not MIN_BLOCK <= p.minutes <= MAX_BLOCK:
            errors.append(f"{p.key}: bloque de {p.minutes} min fuera de {MIN_BLOCK}-{MAX_BLOCK}.")
        if p.start < ws or p.end > we:
            errors.append(f"{p.key}: {p.start:%H:%M}-{p.end:%H:%M} fuera del horario laboral.")
        for e in events:
            if overlaps(p.start, p.end, e.start, e.end):
                errors.append(f"{p.key}: pisa la reunión '{e.subject}' ({e.start:%H:%M}-{e.end:%H:%M}).")

    for i, a in enumerate(plan):
        for b in plan[i + 1 :]:
            if overlaps(a.start, a.end, b.start, b.end):
                errors.append(f"{a.key} y {b.key}: bloques superpuestos.")

    if not plan and issues and any(e - s >= timedelta(minutes=DEFAULT_BLOCK) for s, e in free_gaps(day, busy_from(events))):
        errors.append(f"plan vacío: hay {len(issues)} ticket(s) abierto(s) y huecos libres; proponé al menos un bloque.")
    return errors


def _short(text: str) -> str:
    return (text[:60] + "…") if len(text) > 60 else text


def validate_claims(claims: list[Claim], known: set[str], allowed: tuple[str, ...] | None = None,
                    max_items: int | None = None) -> list[str]:
    """Every claim: non-empty, ≥1 citation, every citation (also inline ones) exists, no URLs."""
    errors: list[str] = []
    if max_items is not None and len(claims) > max_items:
        errors.append(f"demasiadas afirmaciones ({len(claims)} > {max_items}).")
    for c in claims:
        label = _short(c.text)
        if not c.text.strip():
            errors.append("afirmación vacía.")
        if len(c.text) > MAX_CLAIM_CHARS:
            errors.append(f"'{label}': supera {MAX_CLAIM_CHARS} caracteres.")
        if not c.cites:
            errors.append(f"'{label}': afirmación sin cita.")
        for cid in c.cites:
            if cid not in known:
                errors.append(f"'{label}': cita {cid} inexistente en los datos (inventada).")
            elif allowed and not cid.startswith(tuple(p + ":" for p in allowed)):
                errors.append(f"'{label}': no puede citar {cid} (solo {', '.join(allowed)}).")
        for tok in CITE_TOKEN.findall(c.text):
            if tok not in known:
                errors.append(f"'{label}': menciona {tok}, que no existe en los datos.")
        if has_url(c.text):
            errors.append(f"'{label}': contiene un enlace/URL (no permitido).")
    return errors


def validate_links(links: list[GoalLink], evidence: set[str], goal_ids: set[str]) -> list[str]:
    """Goal links: the goal exists and at least one citation is real evidence (not only the goal)."""
    errors: list[str] = []
    for ln in links:
        label = _short(ln.text)
        if ln.goal not in goal_ids:
            errors.append(f"'{label}': el objetivo {ln.goal} no existe.")
        if not [c for c in ln.cites if not c.startswith("goal:")]:
            errors.append(f"'{label}': debe citar evidencia (jira/cal/mail/chat), no solo el objetivo.")
    errors += validate_claims([Claim(ln.text, ln.cites) for ln in links], evidence | goal_ids)
    return errors


def validate_report(report) -> list[str]:
    """Final gate over the whole report: every statement cites ids that exist in the data."""
    known = report.known_ids
    errors = validate_claims(report.advanced, known)
    errors += validate_links(report.goal_links, known - report.goal_ids, report.goal_ids)
    errors += validate_claims([Claim(p.reason, (p.cite,)) for p in report.plan], known)
    errors += validate_claims(getattr(report, "carried", []), known)
    return errors
