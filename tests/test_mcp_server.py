"""MCP server: tool surface, input validation and data framing (offline only)."""

import asyncio

import pytest

pytest.importorskip("mcp")
from daily_digest import cli, mcp_server  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never write demo digests or traces into the real _local-only/ during tests."""
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "DIGESTS", tmp_path / "digests")
    monkeypatch.setattr(mcp_server, "ROOT", tmp_path)
    monkeypatch.setattr(mcp_server, "DIGESTS", tmp_path / "digests")


def test_exposes_three_tools_with_read_only_hints():
    tools = {t.name: t for t in asyncio.run(mcp_server.server.list_tools())}
    assert set(tools) == {"list_digests", "get_digest", "run_digest"}
    assert tools["get_digest"].annotations.read_only_hint is True
    assert tools["run_digest"].annotations.read_only_hint is False


@pytest.mark.parametrize("bad", ["../.env", "..\\..\\.env", "2026-10-09/../../x", "hoy"])
def test_get_digest_rejects_paths(bad):
    assert mcp_server.get_digest(bad) == "Fecha inválida: usá AAAA-MM-DD."


def test_run_digest_defaults_to_offline_demo_and_frames_output():
    out = mcp_server.run_digest("2026-10-09")
    assert out.startswith(mcp_server.FRAME) and "Datos de ejemplo" in out and "llamadas al modelo: 0" in out
    assert mcp_server.list_digests() == ["2026-10-09-demo"]
    assert "no hay digests reales" in mcp_server.get_digest().lower()  # demos are never served as "latest real"
    assert "Datos de ejemplo" in mcp_server.get_digest("2026-10-09-demo")
