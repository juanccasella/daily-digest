"""LangGraph orchestrator.

START ─┬─ fetch_jira ─────────┐
       ├─ fetch_jira_changes ─┤
       ├─ fetch_calendar ─────┤   (code, in parallel; a failing source becomes a warning)
       ├─ fetch_mail ─────────┼─ facts (code) ─┬─ read_untrusted (agent a) ─ link_goals (agent b) ─┐
       ├─ fetch_chats ────────┤                └─ plan (agent c) ────────────────────────────────────┴─ render (code: final critic)
       └─ load_goals ─────────┘

Each agent runs its own critic loop (agents.run_agent): propose → validate in code → feedback
(max 3 attempts) → deterministic fallback, reported as a warning.
"""

import operator
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from . import goals as goals_mod
from .agents import link_goals, plan_day, read_untrusted
from .llm import make_llm
from .models import Claim, Event, Goal, GoalLink, Issue, JiraChange, Message, PlanItem
from .report import Report, advanced_from_code, finalize
from .security import looks_like_injection, sanitize
from .sources import MissingConfig, SourceBlocked, StaticSources, fixture_data
from .trace import NULL
from .window import Window, resolve


def _merge(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class State(TypedDict, total=False):
    day: date
    window: Window
    offline: bool
    use_llm: bool
    m365: str
    issues: list[Issue]
    changes: list[JiraChange]
    events_today: list[Event]
    events_window: list[Event]
    mails: list[Message]
    chats: list[Message]
    goals: list[Goal]
    goals_source: str
    advanced: list[Claim]
    reader_claims: list[Claim]
    links: list[GoalLink]
    plan: list[PlanItem]
    warnings: Annotated[list[str], operator.add]
    provenance: Annotated[dict, _merge]
    attempts: Annotated[dict, _merge]
    report: Report
    errors: list[str]
    source: str  # planner provenance (kept for backwards compatibility)
    digest: str


# --- dependencies (injected through config so evals can swap sources and model) -------------

def _cfg(config: RunnableConfig | None) -> dict:
    return (config or {}).get("configurable", {}) if config else {}


def _window(s: State) -> Window:
    return s.get("window") or resolve(s["day"])


def _sources(s: State, config):
    src = _cfg(config).get("sources")
    if src is not None:
        return src
    if s.get("offline"):
        return StaticSources(fixture_data(), s["day"], _window(s))
    from .sources import RealSources

    return RealSources(s.get("m365", "auto"), _tracer(config))


def _llm(s: State, config):
    cfg = _cfg(config)
    if "llm" in cfg:
        return cfg["llm"]
    return make_llm() if s.get("use_llm") else None


def _tracer(config):
    return _cfg(config).get("tracer") or NULL


def _degraded(name: str, e: Exception) -> str:
    if isinstance(e, SourceBlocked):
        return f"{name}: acceso bloqueado — {e}"
    if isinstance(e, MissingConfig):
        return f"{name}: faltan credenciales en .env ({e})"
    return f"{name}: no disponible ({type(e).__name__}: {str(e)[:160]})"


def _safe(name: str, fn, empty):
    try:
        return fn(), None
    except Exception as e:  # a failing source degrades the report, it never aborts it
        return empty, _degraded(name, e)


def _node(name: str):
    def deco(fn):
        def wrapped(s: State, config: RunnableConfig):
            with _tracer(config).span(f"node {name}", **{"digest.node": name}) as span:
                out = fn(s, config)
                span.set(**{f"digest.out.{k}": len(v) for k, v in out.items() if isinstance(v, list)})
                return out
        wrapped.__name__ = name
        return wrapped
    return deco


# --- fetch (code) ---------------------------------------------------------------------------

@_node("fetch_jira")
def fetch_jira(s, config):
    items, warn = _safe("jira", lambda: _sources(s, config).issues(), [])
    return {"issues": items, "warnings": [warn] if warn else []}


@_node("fetch_jira_changes")
def fetch_jira_changes(s, config):
    items, warn = _safe("jira (cambios)", lambda: _sources(s, config).changes(_window(s)), [])
    return {"changes": items, "warnings": [warn] if warn else []}


@_node("fetch_calendar")
def fetch_calendar(s, config):
    w, day = _window(s), s["day"]
    items, warn = _safe("calendario", lambda: _sources(s, config).events(min(w.start, day), max(w.end, day)), [])
    return {"events_window": [e for e in items if w.contains(e.start)],
            "events_today": [e for e in items if e.start.date() == day],
            "warnings": [warn] if warn else []}


@_node("fetch_mail")
def fetch_mail(s, config):
    items, warn = _safe("mails", lambda: _sources(s, config).mails(_window(s)), [])
    return {"mails": items, "warnings": [warn] if warn else []}


@_node("fetch_chats")
def fetch_chats(s, config):
    w = _window(s)
    try:
        src = _sources(s, config)
        return {"chats": src.chats(w), "warnings": []}
    except SourceBlocked as e:
        try:
            items, origin = src.chats_export(w)
        except Exception as ex:  # a corrupt export must not take the whole report down
            return {"chats": [], "warnings": [f"chats: acceso bloqueado — {e}; además el export local es inválido "
                                              f"({type(ex).__name__}: {str(ex)[:120]}). El informe no incluye chats."]}
        if not items:
            return {"chats": [], "warnings": [f"chats: acceso bloqueado — {e}; {origin}. El informe no incluye chats."]}
        return {"chats": items, "provenance": {"chats": "export"},
                "warnings": [f"chats: acceso bloqueado — {e}. Se usó el adaptador alternativo: {origin} "
                             f"({len(items)} mensajes). Limitación documentada en el README."]}
    except Exception as e:  # same degradation as every other source, without the export fallback
        return {"chats": [], "warnings": [_degraded("chats", e)]}


@_node("load_goals")
def load_goals(s, config):
    given = _cfg(config).get("goals")
    if given is not None:
        goals, origin = given
    else:
        try:
            goals, origin = goals_mod.load(offline=bool(s.get("offline")))
        except ValueError as e:
            return {"goals": [], "goals_source": "inválido", "warnings": [f"objetivos: archivo inválido ({e})"]}
    warn = [] if goals else ["objetivos: no hay objetivos cargados; la sección 'Ayudó a objetivos' queda vacía."]
    return {"goals": goals, "goals_source": origin, "warnings": warn}


# --- facts (code) + agents ------------------------------------------------------------------

@_node("facts")
def facts(s, config):
    warns = []
    for m in s.get("mails", []) + s.get("chats", []):
        if looks_like_injection(f"{m.subject} {m.preview}"):
            warns.append(f"seguridad: posible inyección de prompt en {m.cite} (de {sanitize(m.sender, 60)}). "
                         "Se trató como dato y no se obedeció.")
    # Ticket summaries and meeting subjects are also written by third parties.
    for item in s.get("issues", []) + s.get("changes", []):
        if looks_like_injection(item.summary):
            warns.append(f"seguridad: posible inyección de prompt en el resumen de {item.cite}. Se trató como dato.")
    for e in s.get("events_today", []) + s.get("events_window", []):
        if looks_like_injection(e.subject):
            warns.append(f"seguridad: posible inyección de prompt en la reunión {e.cite}. Se trató como dato.")
    return {"advanced": advanced_from_code(s.get("changes", []), s.get("events_window", [])), "warnings": warns}


def _agent_warning(name: str, res) -> list[str]:
    if res.source != "heuristic-fallback":
        return []
    last = res.errors[0] if res.errors else "sin detalle"
    if last.startswith("falló la llamada al modelo"):
        return [f"{name}: modelo no disponible ({sanitize(last, 160)}); se usó el respaldo heurístico."]
    return [f"{name}: el modelo no convergió en {res.attempts} intento(s); se usó el respaldo heurístico "
            f"(último error: {sanitize(last, 160)})."]


@_node("read_untrusted")
def read_node(s, config):
    msgs = s.get("mails", []) + s.get("chats", [])
    res = read_untrusted(_llm(s, config), _tracer(config), msgs, _window(s).label())
    return {"reader_claims": res.value, "provenance": {"reader": res.source}, "attempts": {"reader": res.attempts},
            "warnings": _agent_warning("lector de mails/chats", res)}


@_node("link_goals")
def link_node(s, config):
    # The reader's heuristic fallback copies (sanitized) third-party text: keep it out of the linker's
    # context so only model-produced, validated claims cross the quarantine boundary.
    reader_ok = s.get("provenance", {}).get("reader") in ("llm", "llm-after-retry")
    evidence = s.get("advanced", []) + (s.get("reader_claims", []) if reader_ok else [])
    res = link_goals(_llm(s, config), _tracer(config), s.get("goals", []), evidence)
    return {"links": res.value, "provenance": {"linker": res.source}, "attempts": {"linker": res.attempts},
            "warnings": _agent_warning("vinculador de objetivos", res)}


@_node("plan")
def plan_node(s, config):
    res = plan_day(_llm(s, config), _tracer(config), s.get("issues", []), s.get("events_today", []), s["day"])
    return {"plan": res.value, "source": res.source, "provenance": {"planner": res.source},
            "attempts": {"planner": res.attempts}, "warnings": _agent_warning("planificador", res)}


@_node("render")
def render(s, config):
    from .render import to_markdown

    report = finalize(s, _window(s))
    return {"report": report, "errors": report.errors, "digest": to_markdown(report)}


def build():
    g = StateGraph(State)
    fetchers = [("fetch_jira", fetch_jira), ("fetch_jira_changes", fetch_jira_changes), ("fetch_calendar", fetch_calendar),
                ("fetch_mail", fetch_mail), ("fetch_chats", fetch_chats), ("load_goals", load_goals)]
    for name, fn in fetchers + [("facts", facts), ("read_untrusted", read_node), ("link_goals", link_node),
                                ("plan", plan_node), ("render", render)]:
        g.add_node(name, fn)
    for name, _ in fetchers:
        g.add_edge(START, name)
    g.add_edge([n for n, _ in fetchers], "facts")
    g.add_edge("facts", "read_untrusted")
    g.add_edge("facts", "plan")
    g.add_edge("read_untrusted", "link_goals")
    g.add_edge(["link_goals", "plan"], "render")
    g.add_edge("render", END)
    return g.compile()


def initial_state(day: date, window: Window, offline: bool, use_llm: bool, m365: str = "auto",
                  warnings: list[str] | None = None) -> State:
    return {"day": day, "window": window, "offline": offline, "use_llm": use_llm, "m365": m365,
            "warnings": list(warnings or []), "provenance": {}, "attempts": {}}
