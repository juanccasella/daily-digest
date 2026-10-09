"""Export the offline demo report (fictional fixtures) to web/demo.json for the static deploy.

    python scripts/export_demo.py

Only fixture data goes into web/: the public deploy never contains real data.
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daily_digest.graph import build, initial_state  # noqa: E402
from daily_digest.webdata import report_json  # noqa: E402
from daily_digest.window import resolve  # noqa: E402

DAY = date(2026, 10, 9)
out = build().invoke(initial_state(DAY, resolve(DAY), offline=True, use_llm=False))
assert out["report"].offline and not out["errors"], out["errors"]
(ROOT / "web" / "demo.json").write_text(json.dumps(report_json(out["report"]), ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
print("web/demo.json listo (datos ficticios)")
