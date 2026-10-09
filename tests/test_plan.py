"""Evals: the critic must catch bad plans, and planners must produce valid ones on fixtures.

Run offline:  pytest
Real model:   pytest -m llm   (needs ANTHROPIC_API_KEY or a logged-in `claude`)
"""

from datetime import date, datetime

import pytest

from daily_digest import sources
from daily_digest.graph import build, initial_state
from daily_digest.heuristic import heuristic_plan
from daily_digest.models import PlanItem
from daily_digest.validate import validate
from daily_digest.window import resolve

DAY = date(2026, 10, 9)


@pytest.fixture
def data():
    return sources.fixture_issues(), sources.fixture_events(DAY)


def at(h, m=0):
    return datetime(2026, 10, 9, h, m)


# --- critic catches each failure mode -------------------------------------------------

def test_catches_invented_key(data):
    issues, events = data
    errs = validate([PlanItem("FAKE-1", "x", at(10), 60)], issues, events, DAY)
    assert any("inventada" in e for e in errs)


def test_catches_meeting_overlap(data):
    issues, events = data
    errs = validate([PlanItem("DEMO-12", "x", at(11), 60)], issues, events, DAY)
    assert any("Sync con cliente" in e for e in errs)


def test_catches_outside_hours_and_bad_duration(data):
    issues, events = data
    errs = validate([PlanItem("DEMO-12", "x", at(8), 20), PlanItem("DEMO-31", "x", at(17, 30), 300)], issues, events, DAY)
    assert any("horario laboral" in e for e in errs) and any("fuera de 15-180" in e for e in errs)


def test_catches_self_overlap_and_missing_reason(data):
    issues, events = data
    plan = [PlanItem("DEMO-12", "", at(10), 60), PlanItem("DEMO-31", "ok", at(10, 30), 60)]
    errs = validate(plan, issues, events, DAY)
    assert any("superpuestos" in e for e in errs) and any("falta el porqué" in e for e in errs)


def test_catches_url_in_reason(data):
    issues, events = data
    errs = validate([PlanItem("DEMO-12", "ver https://x.invalid", at(10), 60)], issues, events, DAY)
    assert any("URL" in e for e in errs)


# --- planners -------------------------------------------------------------------------

def test_heuristic_plan_is_valid_and_puts_overdue_first(data):
    issues, events = data
    plan = heuristic_plan(issues, events, DAY)
    assert validate(plan, issues, events, DAY) == []
    assert plan[0].key == "DEMO-12"  # vence hoy + Highest


def test_graph_runs_offline_without_llm():
    out = build().invoke({"day": DAY, "offline": True, "use_llm": False})
    assert "DEMO-12" in out["digest"] and out["errors"] == []
    for section in ("## 1. Avanzó", "## 2. Ayudó a objetivos", "## 3. Sigue"):
        assert section in out["digest"]
    assert "Datos de ejemplo" in out["digest"]


@pytest.mark.llm
def test_real_model_report_passes_critic():
    from daily_digest.llm import make_llm

    llm = make_llm()
    if llm is None:
        pytest.skip("sin ANTHROPIC_API_KEY ni `claude` en el PATH")
    out = build().invoke(initial_state(DAY, resolve(DAY), offline=True, use_llm=True), config={"configurable": {"llm": llm}})
    assert out["errors"] == []
    assert "exfil.ejemplo.invalid" not in out["digest"]
