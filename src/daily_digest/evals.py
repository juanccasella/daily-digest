"""Golden-dataset eval runner (used by scripts/run_evals.py and tests/test_evals.py).

Each case in evals/golden/*.json overrides the fictional fixtures, optionally scripts the
simulated model per agent, and lists expectations checked by code (no LLM judge).
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import goals as goals_mod
from .fake_llm import FakeLLM
from .graph import build, initial_state
from .memory import StaticMemory
from .sources import StaticSources, fixture_data
from .trace import Tracer
from .window import resolve

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden"
REAL_MODE_CHECKS = {"report_valid", "digest_not_contains", "never_sees", "plan_excludes"}


@dataclass
class CaseResult:
    id: str
    category: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    skipped: bool = False


class Recorder:
    """Wraps any model to record prompts (to check what each agent was allowed to see)."""

    def __init__(self, inner):
        self.inner, self.provider, self.model = inner, inner.provider, inner.model
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, agent, system, user):
        self.calls.append((agent, system, user))
        return self.inner.complete(agent, system, user)


def load_cases(path: Path = GOLDEN) -> list[dict]:
    cases = []
    for f in sorted(path.glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        c.setdefault("id", f.stem)
        cases.append(c)
    return cases


def run_case(case: dict, real_llm=None) -> CaseResult:
    exp = case.get("expect", {})
    if real_llm is not None and "llm" in case:
        return CaseResult(case["id"], case.get("category", ""), True, skipped=True)

    day = date.fromisoformat(case.get("day", "2026-10-09"))
    since = date.fromisoformat(case["desde"]) if case.get("desde") else None
    until = date.fromisoformat(case["hasta"]) if case.get("hasta") else None
    window = resolve(day, since, until)
    data = fixture_data()
    data.update(case.get("data", {}))
    if "goals_md" in case:
        goals = (goals_mod.parse(case["goals_md"]), "caso de eval")
    else:
        goals = (goals_mod.parse(goals_mod.FIXTURE.read_text(encoding="utf-8")), "goals.md")

    use_llm = case.get("use_llm", True)
    llm = Recorder(real_llm if real_llm is not None else FakeLLM(case.get("llm"))) if use_llm else None
    out = build().invoke(
        initial_state(day, window, offline=True, use_llm=use_llm),
        config={"configurable": {"sources": StaticSources(data, day, window), "llm": llm,
                                 "tracer": Tracer(None), "goals": goals,
                                 "memory": StaticMemory(data.get("previous_plan", []))}},
    )
    checks = exp if real_llm is None else {k: v for k, v in exp.items() if k in REAL_MODE_CHECKS}
    return CaseResult(case["id"], case.get("category", ""), *_check(checks, out, llm))


def _check(exp: dict, out: dict, llm) -> tuple[bool, list[str]]:
    f: list[str] = []
    r, digest, warnings = out["report"], out["digest"], out["report"].warnings
    if exp.get("report_valid", True) and out["errors"]:
        f.append(f"informe inválido: {out['errors'][:3]}")
    for k, v in exp.get("provenance", {}).items():
        if r.provenance.get(k) != v:
            f.append(f"provenance[{k}]={r.provenance.get(k)!r}, esperado {v!r}")
    for k, v in exp.get("attempts", {}).items():
        if r.attempts.get(k) != v:
            f.append(f"attempts[{k}]={r.attempts.get(k)!r}, esperado {v!r}")
    for s in exp.get("warnings_contain", []):
        if not any(s in w for w in warnings):
            f.append(f"falta aviso con {s!r}")
    for s in exp.get("no_warnings_contain", []):
        if any(s in w for w in warnings):
            f.append(f"aviso inesperado con {s!r}")
    for s in exp.get("digest_contains", []):
        if s not in digest:
            f.append(f"el informe no contiene {s!r}")
    for s in exp.get("digest_not_contains", []):
        if s.lower() in digest.lower():
            f.append(f"el informe contiene {s!r}")
    for cid in exp.get("cites_include", []):
        if f"[{cid}]" not in digest:
            f.append(f"falta la cita {cid}")
    counts = {"advanced": len(r.advanced), "links": len(r.goal_links), "plan": len(r.plan)}
    for name, n in counts.items():
        if f"{name}_min" in exp and n < exp[f"{name}_min"]:
            f.append(f"{name}={n} < {exp[f'{name}_min']}")
        if f"{name}_max" in exp and n > exp[f"{name}_max"]:
            f.append(f"{name}={n} > {exp[f'{name}_max']}")
    if "plan_first" in exp and (not r.plan or sorted(r.plan, key=lambda p: p.start)[0].key != exp["plan_first"]):
        f.append(f"el primer bloque no es {exp['plan_first']}")
    for key in exp.get("plan_excludes", []):
        if any(p.key == key for p in r.plan):
            f.append(f"el plan incluye {key}")
    if "window_label" in exp and r.window.label() != exp["window_label"]:
        f.append(f"ventana {r.window.label()!r}, esperada {exp['window_label']!r}")
    calls = llm.calls if llm is not None else []
    rp = exp.get("reader_prompt")
    if rp:
        prompts = [u for a, _, u in calls if a == "reader"]
        if not prompts:
            f.append("el lector no fue invocado")
        for u in prompts[:1]:
            for s, n in rp.get("count", {}).items():
                if u.count(s) != n:
                    f.append(f"el prompt del lector tiene {u.count(s)}× {s!r}, esperado {n}")
    for agent, forbidden in exp.get("never_sees", {}).items():
        for a, system, user in calls:
            if a == agent and any(s.lower() in (system + user).lower() for s in forbidden):
                f.append(f"el agente {agent} vio texto crudo no confiable")
                break
    return not f, f


def report(results: list[CaseResult], k: int = 1) -> str:
    lines = ["EVAL REPORT: daily-digest (golden dataset)"]
    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        by_cat.setdefault(r.category or "otros", []).append(r)
    for cat, rs in by_cat.items():
        ok = sum(r.passed for r in rs if not r.skipped)
        run = sum(not r.skipped for r in rs)
        lines.append(f"{cat.capitalize()}: {ok}/{run}" + (f" ({len(rs) - run} omitidos)" if run < len(rs) else ""))
        for r in rs:
            state = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
            lines.append(f"  {r.id}: {state}" + ("" if r.passed else f" — {'; '.join(r.failures)}"))
    run = [r for r in results if not r.skipped]
    rate = 100 * sum(r.passed for r in run) / len(run) if run else 0.0
    lines.append(f"pass@{k}: {rate:.0f}% ({sum(r.passed for r in run)}/{len(run)}) | Estado: "
                 + ("LISTO" if rate == 100 else "NO LISTO"))
    return "\n".join(lines)
