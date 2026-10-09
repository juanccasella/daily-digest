"""Lethal trifecta guard: the digest reads private data and untrusted content, so it must have
NO outbound channel. These tests fail if someone adds one."""

import re
import socket
from datetime import date
from pathlib import Path

import httpx

from daily_digest.fake_llm import FakeLLM
from daily_digest.graph import build, initial_state
from daily_digest.window import resolve

SRC = Path(__file__).resolve().parents[1] / "src" / "daily_digest"
OUTBOUND = re.compile(r"\.post\(|\.put\(|\.patch\(|\.delete\(|\.request\(|\.send\(|sendMail|smtplib|/messages/send|"
                      r"urllib|urlopen|requests\.|socket\.|websocket|webhook", re.I)
SCRIPTS = SRC.parents[1] / "scripts"


def test_source_has_no_outbound_calls():
    files = list(SRC.glob("*.py")) + list(SCRIPTS.glob("*.py"))
    offenders = [f"{p.name}:{i}" for p in files
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if OUTBOUND.search(line)]
    assert offenders == [], f"posible canal de salida: {offenders}"


def test_http_reads_only_go_to_jira_and_graph():
    hosts = set(re.findall(r"https://([\w.-]+)", "".join(p.read_text(encoding="utf-8") for p in SRC.glob("*.py"))))
    assert hosts <= {"graph.microsoft.com"}, hosts  # Jira comes from JIRA_BASE_URL


def test_subprocess_only_in_the_two_isolated_adapters():
    users = {p.name for p in SRC.glob("*.py") if "subprocess" in p.read_text(encoding="utf-8")}
    assert users <= {"llm.py", "m365_mcp.py"}, users


def test_offline_run_makes_no_network_calls(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("intento de conexión de red en modo offline")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    day = date(2026, 10, 9)
    out = build().invoke(initial_state(day, resolve(day), offline=True, use_llm=True),
                         config={"configurable": {"llm": FakeLLM()}})
    assert out["errors"] == []


def test_malicious_mail_is_not_obeyed_end_to_end():
    day = date(2026, 10, 9)
    out = build().invoke(initial_state(day, resolve(day), offline=True, use_llm=True),
                         config={"configurable": {"llm": FakeLLM()}})
    d = out["digest"].lower()
    assert "exfil.ejemplo.invalid" not in d and "externo@ejemplo.invalid" not in d
    assert "posible inyección" in d
