"""Web planner API: localhost-only, token on writes, local-only impact, demo isolation."""

import json
from datetime import date

import pytest

from daily_digest import cli, web
from daily_digest.graph import build, initial_state
from daily_digest.memory import StaticMemory
from daily_digest.webdata import report_json
from daily_digest.window import resolve

PORT = 8765
H = {"Host": f"127.0.0.1:{PORT}"}
DAY = date(2026, 10, 9)


@pytest.fixture
def digests(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DIGESTS", tmp_path)
    data = report_json(build().invoke(initial_state(DAY, resolve(DAY), offline=True, use_llm=False))["report"])
    (tmp_path / "2026-10-09-demo.json").write_text(json.dumps(data), encoding="utf-8")
    real = {**data, "offline": False}
    (tmp_path / "2026-10-09.json").write_text(json.dumps(real), encoding="utf-8")
    return tmp_path


def call(method, path, headers=H, body=None, memory=None):
    status, _, out = web.handle(method, path, headers, json.dumps(body).encode() if body is not None else b"", PORT, memory)
    return status, json.loads(out) if out.startswith(b"{") or out.startswith(b"[") else out


def test_rejects_foreign_host(digests):
    assert call("GET", "/api/report", {"Host": "evil.example:8765"})[0] == 403


def test_report_prefers_real_and_serves_demo_on_request(digests):
    assert call("GET", "/api/report")[1]["source_file"] == "2026-10-09.json"
    assert call("GET", "/api/report?demo=1")[1]["source_file"] == "2026-10-09-demo.json"


def test_post_requires_token(digests):
    assert call("POST", "/api/tasks/DEMO-12/status", body={"status": "done"})[0] == 403


def test_mark_done_updates_report_and_memory(digests):
    mem = StaticMemory([])
    status, data = call("POST", "/api/tasks/DEMO-12/status", {**H, "X-Digest-Token": web.TOKEN}, {"status": "done"}, mem)
    assert status == 200 and data["task"]["done"] is True
    assert mem.done_keys() == {"DEMO-12"}
    saved = json.loads((digests / "2026-10-09.json").read_text(encoding="utf-8"))
    assert next(t for t in saved["tasks"] if t["key"] == "DEMO-12")["done"] is True


def test_demo_never_touches_memory(digests):
    mem = StaticMemory([])
    call("POST", "/api/tasks/DEMO-12/status", {**H, "X-Digest-Token": web.TOKEN}, {"status": "done", "demo": True}, mem)
    assert mem.done_keys() == set()


@pytest.mark.parametrize("key,status", [("../x", "done"), ("DEMO-12", "deleted"), ("NOPE-1", "done")])
def test_rejects_bad_keys_and_statuses(digests, key, status):
    assert call("POST", f"/api/tasks/{key}/status", {**H, "X-Digest-Token": web.TOKEN}, {"status": status})[0] in (400, 404)


def test_done_task_is_not_planned_nor_carried():
    """The impact of 'Marcar como hecha': next run neither plans nor carries it over."""
    mem = StaticMemory([{"key": "DEMO-08"}])
    mem.set_status(DAY, "DEMO-08", "done")
    mem.set_status(DAY, "DEMO-12", "done")
    out = build().invoke(initial_state(DAY, resolve(DAY), offline=True, use_llm=False), config={"configurable": {"memory": mem}})
    planned = {p.key for p in out["report"].plan}
    assert "DEMO-12" not in planned and "DEMO-08" not in planned and not out["report"].carried
    tasks = {t["key"]: t for t in report_json(out["report"])["tasks"]}
    assert tasks["DEMO-12"]["done"] and tasks["DEMO-08"]["done"]


def test_index_gets_token_injected(digests):
    status, html = call("GET", "/")
    assert status == 200 and web.TOKEN.encode() in html and b"__DIGEST_TOKEN__" not in html


def test_ui_never_uses_innerhtml():
    src = (web.WEB / "index.html").read_text(encoding="utf-8")
    assert ".innerHTML" not in src and ".outerHTML" not in src and "insertAdjacentHTML" not in src
    assert "document.write" not in src and "eval(" not in src
