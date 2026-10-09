"""Per-run JSONL trace: one span per graph node and per model call.

Span names and attributes follow the OpenTelemetry GenAI semantic conventions where they apply
(`invoke_agent <agent>`, `chat <model>`, `gen_ai.usage.input_tokens`, ...). Traces do not store
prompts, answers or message bodies; error attributes may include short, truncated fragments
(e.g. a validator error quoting 60 chars of a claim), so traces live in `_local-only/traces/`
(gitignored) and are treated as private data.
"""

import contextvars
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("span", default=None)


class Span:
    def __init__(self, name: str, attributes: dict):
        self.name = name
        self.attributes = dict(attributes)
        self.status = "ok"

    def set(self, **attrs) -> None:
        self.attributes.update(attrs)

    def error(self, message: str) -> None:
        self.status = "error"
        self.attributes["error.message"] = message


class Tracer:
    def __init__(self, path: Path | None = None):
        self.trace_id = uuid.uuid4().hex
        self.path = path
        self.spans: list[dict] = []
        self._lock = threading.Lock()

    @contextmanager
    def span(self, name: str, **attributes):
        span_id = uuid.uuid4().hex[:16]
        parent = _current.get()
        token = _current.set(span_id)
        s = Span(name, attributes)
        start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            yield s
        except Exception as e:  # recorded, then re-raised: the trace never swallows errors
            s.error(f"{type(e).__name__}: {e}"[:300])
            raise
        finally:
            _current.reset(token)
            rec = {
                "trace_id": self.trace_id,
                "span_id": span_id,
                "parent_span_id": parent,
                "name": name,
                "start": started_at,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "status": s.status,
                "attributes": s.attributes,
            }
            with self._lock:
                self.spans.append(rec)

    def flush(self) -> Path | None:
        if not self.path:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for rec in self.spans:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return self.path

    def totals(self) -> dict:
        tin = sum(s["attributes"].get("gen_ai.usage.input_tokens", 0) or 0 for s in self.spans)
        tout = sum(s["attributes"].get("gen_ai.usage.output_tokens", 0) or 0 for s in self.spans)
        costs = [s["attributes"].get("digest.cost_usd") for s in self.spans if s["name"].startswith(("chat ", "execute_tool "))]
        known = [c for c in costs if c is not None]
        return {"input_tokens": tin, "output_tokens": tout,
                "cost_usd": round(sum(known), 6) if known else None, "model_calls": len(costs)}


NULL = Tracer(None)


def for_run(root: Path, day) -> Tracer:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    t = Tracer(None)
    t.path = root / "_local-only" / "traces" / f"{day}-{stamp}-{t.trace_id[:6]}.jsonl"
    return t
