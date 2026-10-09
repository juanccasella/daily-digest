import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import trace
from .graph import build, initial_state
from .llm import make_llm
from .memory import SqliteMemory
from .window import resolve

ROOT = Path(__file__).resolve().parents[2]


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

    window = resolve(a.date, a.desde, a.hasta)
    llm = None if a.no_llm else make_llm(a.llm)
    warnings = []
    if not a.no_llm and llm is None:
        warnings.append("modelo no disponible (sin ANTHROPIC_API_KEY ni `claude`): todo el informe es heurístico.")

    tracer = trace.for_run(ROOT, a.date)
    config = {"tracer": tracer, "llm": llm}
    if not a.offline:
        config["memory"] = SqliteMemory()
    try:
        with tracer.span("invoke_workflow daily-digest", **{"digest.offline": a.offline, "digest.window": window.label(),
                                                            "digest.llm": type(llm).__name__ if llm else "none"}):
            out = build().invoke(initial_state(a.date, window, a.offline, llm is not None, a.fuentes_m365, warnings),
                                 config={"configurable": config})
    finally:  # the trace is most useful exactly when the run blows up
        path = tracer.flush()
    print(out["digest"])
    if "memory" in config and not out["errors"]:  # remember today's plan for tomorrow's carry-over
        config["memory"].save_plan(a.date, out["report"].plan, out.get("source", ""))

    dest = ROOT / "_local-only" / "digests"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{a.date}.md").write_text(out["digest"], encoding="utf-8")
    t = tracer.totals()
    # `claude -p` reports the API-equivalent cost; with a Claude subscription it is not billed (it uses plan quota).
    cost = f"{t['cost_usd']} USD equivalente API" if t["cost_usd"] is not None else "n/d"
    print(f"\n(traza: {path.relative_to(ROOT)} · llamadas al modelo: {t['model_calls']} · tokens in/out: "
          f"{t['input_tokens']}/{t['output_tokens']} · costo: {cost})", file=sys.stderr)
    # Exit code for schedulers: 1 = invalid report, 3 = valid but degraded (warnings), 0 = clean.
    if out["errors"]:
        return 1
    return 3 if out["report"].warnings and not a.offline else 0


if __name__ == "__main__":
    sys.exit(main())
