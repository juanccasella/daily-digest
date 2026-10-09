"""Markdown rendering. Every statement shows its citations as `[id]`."""

from .report import Report
from .scheduling import DEFAULT_BLOCK
from .security import sanitize

LABELS = {"llm": "modelo", "llm-after-retry": "modelo (tras reintento)", "heuristic": "heurístico",
          "heuristic-fallback": "respaldo heurístico", "sin-datos": "sin datos"}


def _cites(cites) -> str:
    return " ".join(f"`[{c}]`" for c in cites)


def _text(text: str) -> str:
    """Model-written text: strip links/HTML and neutralize markdown link/image syntax before rendering."""
    return sanitize(text, 400).replace("[", "(").replace("]", ")").replace("!(", "(")


def to_markdown(r: Report) -> str:
    lines = [f"# Digest del {r.day:%d/%m/%Y}", ""]
    if r.offline:
        lines += ["> **Datos de ejemplo:** este informe usa `fixtures/` ficticios, no datos reales.", ""]
    lines += [f"_Período analizado: {r.window.label()} · objetivos: {r.goals_source or '—'}_", ""]

    if r.warnings:
        lines += ["## Avisos", ""] + [f"- ⚠️ {sanitize(w, 400)}" for w in r.warnings] + [""]

    lines += [f"## 1. Avanzó ({r.window.label()})", ""]
    lines += [f"- {_text(c.text)} {_cites(c.cites)}" for c in r.advanced] or ["- (sin movimientos registrados en el período)"]

    lines += ["", "## 2. Ayudó a objetivos", ""]
    if not r.goals:
        lines.append("- (sin objetivos cargados)")
    for g in r.goals:
        links = [ln for ln in r.goal_links if ln.goal == g.id]
        lines.append(f"- **{g.id}** {g.text}")
        lines += [f"  - {_text(ln.text)} {_cites(ln.cites)}" for ln in links] or ["  - sin avance registrado en el período"]

    lines += ["", f"## 3. Sigue (plan de hoy {r.day:%d/%m})", ""]
    meetings = sorted(r.events_today, key=lambda e: e.start)
    lines.append("**Reuniones:** " + (", ".join(f"{e.start:%H:%M}-{e.end:%H:%M} {sanitize(e.subject, 60)} `[{e.cite}]`"
                                                  for e in meetings) or "sin reuniones"))
    lines.append("")
    by_key = {i.key: i for i in r.issues}
    if r.plan:
        lines += ["| Hora | Ticket | Por qué | Cita |", "|---|---|---|---|"]
        for p in sorted(r.plan, key=lambda p: p.start):
            summary = sanitize(by_key[p.key].summary, 80) if p.key in by_key else ""
            lines.append(f"| {p.start:%H:%M}-{p.end:%H:%M} | {p.key} {summary} | {_text(p.reason)[:200].replace('|', '/')} | `[{p.cite}]` |")
    elif r.issues:
        lines.append(f"- (sin huecos libres de {DEFAULT_BLOCK} min en la jornada: los tickets abiertos quedan en el backlog)")
    else:
        lines.append("- (sin tickets abiertos para planificar)")
    planned = {p.key for p in r.plan}
    rest = [i for i in r.issues if i.key not in planned]
    if rest:
        lines += ["", f"**Backlog sin bloque hoy ({len(rest)}):**"]
        lines += [f"- {i.key} {sanitize(i.summary, 80)} ({i.priority}, actualizado {i.updated:%d/%m}) `[{i.cite}]`" for i in rest]

    prov = r.provenance
    gen = " · ".join(f"{name}: {LABELS.get(prov.get(key), prov.get(key, '—'))}"
                     + (f" ({r.attempts[key]} intento/s)" if r.attempts.get(key) else "")
                     for key, name in (("reader", "lector"), ("linker", "vinculador"), ("planner", "planificador")))
    lines += ["", "---", f"_Generado por: {gen}_"]
    return "\n".join(lines)
