"""Read-only calls against the real services. Requiere credenciales: `pytest -m integration`."""

import os
from datetime import date

import pytest
from dotenv import load_dotenv

from daily_digest.window import resolve

load_dotenv()
pytestmark = pytest.mark.integration
W = resolve(date.today())


@pytest.mark.skipif(not os.getenv("JIRA_API_TOKEN"), reason="requiere credenciales de Jira")
def test_jira_issues_and_changes():
    from daily_digest.sources import jira_changes, jira_issues

    assert isinstance(jira_issues(), list)
    assert all(c.cite.startswith("jira:") for c in jira_changes(W))


@pytest.mark.skipif(not os.getenv("GRAPH_ACCESS_TOKEN"), reason="requiere GRAPH_ACCESS_TOKEN")
def test_graph_sources():
    from daily_digest.sources import SourceBlocked, graph_chats, graph_events, graph_mails

    assert isinstance(graph_events(W.start, W.end), list)
    assert isinstance(graph_mails(W), list)
    try:
        graph_chats(W)
    except SourceBlocked:
        pytest.xfail("Chat.Read bloqueado por el tenant (limitación documentada)")


@pytest.mark.skipif(os.getenv("DIGEST_M365_BACKEND", "mcp") != "mcp", reason="plan B por conector deshabilitado")
def test_m365_via_mcp_connector():
    from daily_digest.llm import find_claude

    if not find_claude():
        pytest.skip("requiere `claude` logueado con el conector Microsoft 365")
    from daily_digest.m365_mcp import M365ViaMCP

    events = M365ViaMCP().events(W.start, W.end)
    assert all(e.cite.startswith("cal:") for e in events)
