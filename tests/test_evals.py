"""Golden dataset as pytest cases (offline, simulated deterministic model)."""

import pytest

from daily_digest.evals import load_cases, run_case

CASES = load_cases()


def test_golden_dataset_size():
    assert len(CASES) >= 25


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case):
    r = run_case(case)
    assert r.passed, r.failures
