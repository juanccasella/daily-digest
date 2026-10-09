"""Model access behind one interface, with three backends:

- `anthropic`:  Claude API via the SDK (needs ANTHROPIC_API_KEY).
- `claude-cli`: `claude -p` (Claude Code non-interactive) with the already logged-in account,
                fully isolated: no tools, no MCP servers, no CLAUDE.md/skills (`--safe-mode`).
- `fake`:       deterministic simulated model for offline evals (see `fake_llm.py`).

The model id always comes from `DIGEST_MODEL`, never hardcoded in the call sites.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .trace import NULL, Tracer

DEFAULT_MODEL = "claude-sonnet-5-5"


def model_id() -> str:
    return os.getenv("DIGEST_MODEL") or DEFAULT_MODEL


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLM(Protocol):
    provider: str
    model: str

    def complete(self, agent: str, system: str, user: str) -> Completion: ...


def _price_estimate(tin: int | None, tout: int | None) -> float | None:
    """Optional: DIGEST_PRICE_INPUT_PER_MTOK / DIGEST_PRICE_OUTPUT_PER_MTOK (USD). No hardcoded prices."""
    pin, pout = os.getenv("DIGEST_PRICE_INPUT_PER_MTOK"), os.getenv("DIGEST_PRICE_OUTPUT_PER_MTOK")
    if not (pin and pout) or tin is None or tout is None:
        return None
    return round(tin * float(pin) / 1e6 + tout * float(pout) / 1e6, 6)


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str | None = None):
        from anthropic import Anthropic

        self.model = model or model_id()
        self._client = Anthropic(timeout=120)

    def complete(self, agent: str, system: str, user: str) -> Completion:
        try:
            msg = self._client.messages.create(
                model=self.model, max_tokens=2000, system=system, messages=[{"role": "user", "content": user}]
            )
        except Exception as e:  # auth, quota, rate limit, timeout, network: infrastructure, not the answer
            raise LLMError(f"API de Anthropic: {type(e).__name__}: {str(e)[:200]}") from e
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        tin, tout = msg.usage.input_tokens, msg.usage.output_tokens
        return Completion(text, msg.model, tin, tout, _price_estimate(tin, tout))


_SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|_KEY)$|^(JIRA_|GRAPH_)", re.I)


def safe_env() -> dict[str, str]:
    """Environment for `claude -p` subprocesses without our credentials (defense in depth: the
    subprocess never needs Jira/Graph/Anthropic secrets; it authenticates with the Claude login)."""
    # CLAUDE_CODE_* (e.g. an OAuth token for headless use) is the CLI's own login: keep it.
    return {k: v for k, v in os.environ.items() if k.upper().startswith("CLAUDE_CODE_") or not _SECRET_ENV.search(k)}


def find_claude() -> str | None:
    """Resolve the real `claude` binary. On Windows npm installs a `claude.CMD` shim; running it
    through cmd.exe truncates arguments at the first newline (multi-line system prompts), which
    silently drops every flag after it — including `--tools ""`. So we call the native exe."""
    override = os.getenv("DIGEST_CLAUDE_EXE")
    if override:
        return override
    exe = shutil.which("claude")
    if exe and exe.lower().endswith((".cmd", ".bat")):
        native = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        return str(native) if native.exists() else None
    return exe


class ClaudeCliLLM:
    """Plan B when there is no API key: `claude -p` with the logged-in Claude account."""

    provider = "anthropic"

    def __init__(self, model: str | None = None, timeout: int = 180):
        exe = find_claude()
        if not exe:
            raise LLMError("No se encontró el ejecutable nativo de `claude` (ver DIGEST_CLAUDE_EXE).")
        self.exe, self.model, self.timeout = exe, model or model_id(), timeout

    def command(self, system: str) -> list[str]:
        return [
            self.exe, "-p",
            "--safe-mode",           # no CLAUDE.md, skills, plugins, hooks or MCP from the user config
            "--tools", "",           # no built-in tools: the model can only answer text
            "--strict-mcp-config",   # and no MCP servers at all
            "--no-session-persistence",
            "--system-prompt", system,
            "--model", self.model,
            "--output-format", "json",
        ]

    def complete(self, agent: str, system: str, user: str) -> Completion:
        try:
            p = subprocess.run(
                self.command(system), input=user, capture_output=True, text=True, encoding="utf-8",
                cwd=tempfile.gettempdir(), timeout=self.timeout, env=safe_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude -p no respondió en {self.timeout} s") from e
        except OSError as e:
            raise LLMError(f"no se pudo ejecutar claude -p: {e}") from e
        if p.returncode != 0:
            raise LLMError(f"claude -p salió con código {p.returncode}: {p.stderr.strip()[:300]}")
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude -p no devolvió JSON ({len(p.stdout)} caracteres de salida)") from e
        if d.get("is_error"):
            raise LLMError(f"claude -p devolvió error: {str(d.get('result'))[:300]}")
        u = d.get("usage") or {}
        tin = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
        models = list((d.get("modelUsage") or {}).keys())
        return Completion(str(d.get("result", "")), models[0] if models else self.model, tin, u.get("output_tokens"),
                          d.get("total_cost_usd"))


def make_llm(backend: str | None = None) -> LLM | None:
    """`auto`: API key → SDK; else `claude` on PATH → CLI; else None (heuristic planners)."""
    backend = (backend or os.getenv("DIGEST_LLM_BACKEND") or "auto").lower()
    if backend == "anthropic":
        return AnthropicLLM()
    if backend == "claude-cli":
        return ClaudeCliLLM()
    if backend == "fake":
        from .fake_llm import FakeLLM

        return FakeLLM()
    if backend != "auto":
        raise ValueError(f"DIGEST_LLM_BACKEND desconocido: {backend}")
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    if find_claude():
        return ClaudeCliLLM()
    return None


def traced_complete(llm: LLM, tracer: Tracer, agent: str, system: str, user: str, attempt: int) -> str:
    tracer = tracer or NULL
    with tracer.span(f"chat {llm.model}", **{
        "gen_ai.operation.name": "chat", "gen_ai.provider.name": llm.provider,
        "gen_ai.request.model": llm.model, "gen_ai.agent.name": agent, "digest.attempt": attempt,
        "digest.backend": type(llm).__name__,
    }) as s:
        t0 = time.perf_counter()
        c = llm.complete(agent, system, user)
        s.set(**{
            "gen_ai.response.model": c.model,
            "gen_ai.usage.input_tokens": c.input_tokens,
            "gen_ai.usage.output_tokens": c.output_tokens,
            "digest.cost_usd": c.cost_usd,
            "digest.latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
        return c.text


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model answer (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(f"la respuesta no contiene JSON: {(text or '')[:120]!r}")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("el JSON debe ser un objeto")
    return data
