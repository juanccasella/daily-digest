"""Local web planner: serves web/index.html and a tiny JSON API over the saved reports.

    daily-digest-web            # http://127.0.0.1:8765

Security (it serves private data and accepts writes):
- binds to 127.0.0.1 only; rejects any Host header that is not localhost (DNS rebinding);
- every POST needs the per-process token embedded in the served page (blocks CSRF from other sites);
- the only write is local: a task's status in the SQLite memory. Nothing is written to Jira or
  sent anywhere (ADR-0003): the UI links to Jira so the human moves the ticket there.
"""

import json
import re
import secrets
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

from . import cli
from .memory import STATUSES, SqliteMemory

WEB = Path(__file__).resolve().parents[2] / "web"
TOKEN = secrets.token_urlsafe(24)
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")
_TASK = re.compile(r"^/api/tasks/([^/]+)/status$")


def _json(status: int, data) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode("utf-8")


def latest_report_path(demo: bool = False) -> Path | None:
    files = sorted(cli.DIGESTS.glob("*.json"), reverse=True)
    real = [f for f in files if not f.stem.endswith("-demo")]
    demos = [f for f in files if f.stem.endswith("-demo")]
    pick = (demos if demo else real) or (demos if not demo else [])
    return pick[0] if pick else None


def handle(method: str, path: str, headers: dict, body: bytes, port: int, memory=None) -> tuple[int, str, bytes]:
    host = (headers.get("Host") or "").lower()
    if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return _json(403, {"error": "host no permitido"})
    route, _, query = path.partition("?")

    if method == "GET" and route in ("/", "/index.html"):
        html = (WEB / "index.html").read_text(encoding="utf-8").replace("__DIGEST_TOKEN__", TOKEN)
        return 200, "text/html; charset=utf-8", html.encode("utf-8")

    if method == "GET" and route == "/api/report":
        p = latest_report_path(demo="demo=1" in query)
        if not p:
            return _json(404, {"error": "todavía no hay informes: corré daily-digest o usá 'Generar demo'"})
        data = json.loads(p.read_text(encoding="utf-8"))
        data["source_file"] = p.name
        return _json(200, data)

    if method != "POST":
        return _json(404, {"error": "no encontrado"})
    if headers.get("X-Digest-Token") != TOKEN:
        return _json(403, {"error": "token inválido"})
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return _json(400, {"error": "JSON inválido"})

    m = _TASK.match(route)
    if m:
        key, status = m.group(1), payload.get("status")
        if not KEY_RE.match(key) or status not in STATUSES:
            return _json(400, {"error": "clave o estado inválido"})
        p = latest_report_path(demo=bool(payload.get("demo")))
        if not p:
            return _json(404, {"error": "no hay informe"})
        data = json.loads(p.read_text(encoding="utf-8"))
        task = next((t for t in data["tasks"] if t["key"] == key), None)
        if task is None:
            return _json(404, {"error": f"{key} no está en el informe"})
        if not data.get("offline"):  # demos never touch the real memory
            (memory or SqliteMemory()).set_status(date.today(), key, status)
        task["done"] = status == "done"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return _json(200, {"ok": True, "task": task})

    if route == "/api/run":
        real = bool(payload.get("real"))
        r = cli.run(date.today(), offline=not real, no_llm=not payload.get("use_model"))
        data = json.loads(r.digest_path.with_suffix(".json").read_text(encoding="utf-8"))
        return _json(200, {**data, "source_file": r.digest_path.with_suffix(".json").name})
    return _json(404, {"error": "no encontrado"})


def serve(port: int = 8765) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                status, ctype, out = _json(413, {"error": "pedido demasiado grande"})
            else:
                status, ctype, out = handle(method, self.path, dict(self.headers), self.rfile.read(n), port)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                                        "style-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *a):  # keep the terminal clean; no request bodies are ever logged
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Planner en http://127.0.0.1:{port}  (Ctrl+C para cortar)")
    httpd.serve_forever()


def main() -> None:
    load_dotenv(cli.ROOT / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)


if __name__ == "__main__":
    main()
