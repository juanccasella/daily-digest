"""Run the golden dataset.

    python scripts/run_evals.py                 # offline, simulated deterministic model (CI / pre-push)
    python scripts/run_evals.py --real --k 3    # real model (API key or `claude -p`); pass@k and pass^k

Exit code 1 if any offline case fails.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from daily_digest.evals import CaseResult, load_cases, report, run_case  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="usar el modelo real en vez del simulado")
    ap.add_argument("--k", type=int, default=1, help="intentos por caso (pass@k / pass^k)")
    ap.add_argument("--only", help="correr solo los casos cuyo id contenga este texto")
    a = ap.parse_args()

    llm = None
    if a.real:
        load_dotenv(ROOT / ".env")
        from daily_digest.llm import make_llm

        llm = make_llm()
        if llm is None:
            print("--real requiere ANTHROPIC_API_KEY o `claude` en el PATH.", file=sys.stderr)
            return 2

    cases = [c for c in load_cases() if not a.only or a.only in c["id"]]
    results, all_k = [], 0
    for c in cases:
        runs = [run_case(c, llm) for _ in range(a.k)]
        if runs[0].skipped:
            results.append(runs[0])
            continue
        any_ok, all_ok = any(r.passed for r in runs), all(r.passed for r in runs)
        all_k += all_ok
        fails = next((r.failures for r in runs if not r.passed), [])
        results.append(CaseResult(c["id"], c.get("category", ""), any_ok, fails))
    print(report(results, a.k))
    run = [r for r in results if not r.skipped]
    if not run:
        print("No se corrió ningún caso (¿--only no coincide con nada?).", file=sys.stderr)
        return 2
    if a.k > 1:
        print(f"pass^{a.k}: {100 * all_k / len(run):.0f}% ({all_k}/{len(run)})")
    return 0 if all(r.passed for r in run) else 1


if __name__ == "__main__":
    sys.exit(main())
