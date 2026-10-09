"""Untrusted-input handling: sanitizing, quarantine delimiting and injection signals.

Mails and chats are DATA, never instructions. Defense in depth:
1. The reader agent has no tools and only sees messages inside a delimited, escaped block.
2. Every LLM output is validated by code (citations, no URLs) before any other agent sees it.
3. The digest has no outbound channel: it only reads sources and writes local files.
4. Injection-looking messages are flagged in the report (signal for the human, not a filter).
"""

import re

from .models import Message

URL_RE = re.compile("|".join([
    r"https?://\S+", r"www\.\S+",
    r"\b(?:mailto|javascript|data|ftp|file|vbscript):\S+",       # other schemes
    r"(?<![\w:])//[\w-]+(?:\.[\w-]+)+\S*",                        # protocol-relative //host/...
    r"!?\[[^\]]*\]\([^)]*\)",                                     # inline links and images
    r"!?\[[^\]]*\]\[[^\]]*\]",                                    # reference-style links and images
    r"<\s*(?:img|a|iframe|script|link|object|embed)\b[^>]*>?",   # raw HTML that loads or links
]), re.I)
TAG_RE = re.compile(r"<[^>]{0,200}>")

_INJECTION = [
    r"ignor\w*\s+(todas?\s+)?(las\s+|tus\s+)?(instrucciones|reglas|indicaciones)",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)",
    r"(system|developer)\s*prompt",
    r"\bsos\s+ahora\b|\byou\s+are\s+now\b",
    r"\b(asistente|assistant|IA|AI)\b.{0,60}\b(envi|mand|send|forward|reenvi)\w*",
    r"</?\s*datos_no_confiables",
    r"(exfiltr|filtr)\w*\s+(los\s+)?datos",
]
INJECTION_RE = re.compile("|".join(_INJECTION), re.I)

OPEN, CLOSE = "<datos_no_confiables>", "</datos_no_confiables>"


def strip_urls(text: str) -> str:
    return URL_RE.sub("[enlace eliminado]", text)


def sanitize(text: str, limit: int = 280) -> str:
    """Plain, single-line, URL-free text safe to show in the report."""
    text = TAG_RE.sub(" ", text or "")
    text = strip_urls(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def has_url(text: str) -> bool:
    return bool(URL_RE.search(text or ""))


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_RE.search(text or ""))


def _escape(text: str) -> str:
    # Neutralize anything that could close or forge the quarantine block.
    return (text or "").replace("<", "‹").replace(">", "›")


def quarantine(messages: list[Message]) -> str:
    """Render messages as a delimited data block. Each line is marked with '│ ' (datamarking)."""
    parts = [OPEN]
    for m in messages:
        parts.append(f'<mensaje id="{m.cite}" canal="{m.channel}" fecha="{m.sent:%Y-%m-%d %H:%M}">')
        parts.append(f"│ de: {_escape(sanitize(m.sender, 80))}")
        parts.append(f"│ asunto: {_escape(sanitize(m.subject, 160))}")
        for line in _escape(sanitize(m.preview, 600)).split("\n"):
            parts.append(f"│ {line}")
        parts.append("</mensaje>")
    parts.append(CLOSE)
    return "\n".join(parts)
