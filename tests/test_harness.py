"""The harness validator must actually catch secrets and real-looking data (not be decorative)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validar", ROOT / "scripts" / "validar.py")
validar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validar)

# Fake values built at runtime so this file itself never contains a matching literal.
SAMPLES = [
    "Authorization: Bearer " + "a" * 30,
    "sk-" + "ant-" + "x" * 30,
    "ATATT3" + "x" * 30,
    "gh" + "p_" + "y" * 36,
    "JIRA_API_TOKEN" + "=" + "z" * 20,
    "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + ".sig",
]


@pytest.mark.parametrize("line", SAMPLES)
def test_secret_patterns_match(line):
    assert validar.SECRETOS.search(line)


def test_env_example_is_clean():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        assert not validar.SECRETOS.search(line), line


@pytest.mark.parametrize("mail,ok", [("x@ejemplo.invalid", True), ("a@example.com", True), ("juan@empresa.com.ar", False)])
def test_fixture_mail_domains(mail, ok):
    assert bool(validar.DOMINIO_OK.search(mail)) is ok
