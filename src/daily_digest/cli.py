import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import trace
from .graph import build, initial_state
from .llm import make_llm
from .memory import SqliteMemory
from .webdata import report_json
from .window import resolve

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = ROOT / "_local-only" / "digests"


@dataclass
class RunResult:
    out: dict
    digest_path: Path
    trace_path: Path
    totals: dict

    @property
    def exit_code(self) -> int:
        """For schedulers: 1 = invalid report, 3 = valid but degraded (warnings), 0 = clean."""
        if self.out["errors"]:
            return 1
        return 3 if self.out["report"].warnings and not self.out["report"].offline else 0


def run(day: date, since: date | None = None, until: date | None = None, offline: bool = False,
        no_llm: bool = False, m365: str = "auto", llm_backend: str | None = None) -> RunResult:
    """One digest run (shared by the CLI and the MCP server)."""
    window = resolve(day, since, until)
    llm = None if no_llm else make_llm(llm_backend)
    warnings = []
    if not no_llm and llm is None:
        warnings.append("modelo no disponible (sin ANTHROPIC_API_KEY ni `claude`): todo el informe es heurístico.")

    tracer = trace.for_run(ROOT, day)
    config = {"tracer": tracer, "llm": llm}
    if not offline:
        config["memory"] = SqliteMemory()
    try:
        with tracer.span("invoke_workflow daily-digest", **{"digest.offline": offline, "digest.window": window.label(),
                                                            "digest.llm": type(llm).__name__ if llm else "none"}):
            out = build().invoke(initial_state(day, window, offline, llm is not None, m365, warnings),
                                 config={"configurable": config})
    finally:  # the trace is most useful exactly when the run blows up
        trace_path = tracer.flush()
    if "memory" in config and not out["errors"]:  # remember today's plan for tomorrow's carry-over
        config["memory"].save_plan(day, out["report"].plan, out.get("source", ""))

    DIGESTS.mkdir(parents=True, exist_ok=True)
    digest_path = DIGESTS / f"{day}{'-demo' if offline else ''}.md"  # a demo never overwrites a real digest
    digest_path.write_text(out["digest"], encoding="utf-8")
    digest_path.with_suffix(".json").write_text(json.dumps(report_json(out["report"]), ensure_ascii=False, indent=1),
                                                encoding="utf-8")  # what the web planner reads
    return RunResult(out, digest_path, trace_path, tracer.totals())


def main() -> int:
    load_dotenv(ROOT / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Daily digest: Jira + calendario + mails + chats → Avanzó / Objetivos / Sigue")
    ap.add_argument("--offline", action="store_true", help="usar fixtures/ ficticios en vez de las fuentes reales")
    ap.add_argument("--no-llm", action="store_true", help="solo planificadores heurísticos (sin modelo)")
    ap.add_argument("--date", type=date.fromisoformat, default=date.today(), help="día a planificar (default: hoy)")
    ap.add_argument("--desde", type=date.fromisoformat, help="inicio del período a resumir (default: día laboral anterior)")
    ap.add_argument("--hasta", type=date.fromisoformat, help="fin del período a resumir (inclusive)")
    ap.add_argument("--fuentes-m365", choices=["auto", "graph", "mcp"], default="auto",
                    help="Microsoft 365 vía Graph (token) o vía conector MCP con `claude -p` (default: auto)")
    ap.add_argument("--llm", choices=["auto", "anthropic", "claude-cli"], default=None,
                    help="modelo vía API (ANTHROPIC_API_KEY) o vía `claude -p` (default: DIGEST_LLM_BACKEND o auto)")
    a = ap.parse_args()

    r = run(a.date, a.desde, a.hasta, a.offline, a.no_llm, a.fuentes_m365, a.llm)
    print(r.out["digest"])
    t = r.totals
    # `claude -p` reports the API-equivalent cost; with a Claude subscription it is not billed (it uses plan quota).
    cost = f"{t['cost_usd']} USD equivalente API" if t["cost_usd"] is not None else "n/d"
    print(f"\n(traza: {r.trace_path.relative_to(ROOT)} · llamadas al modelo: {t['model_calls']} · tokens in/out: "
          f"{t['input_tokens']}/{t['output_tokens']} · costo: {cost})", file=sys.stderr)
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
