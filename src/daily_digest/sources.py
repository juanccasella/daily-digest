"""Data sources. Fetching is CODE, not an agent: deterministic, parallel and testable.

Backends behind one interface (`Sources`):
- StaticSources: fixtures/ (demo, offline) and golden eval cases.
- RealSources:   Jira Cloud REST (issues + changelog) and Microsoft 365, either through
                 Microsoft Graph (needs GRAPH_ACCESS_TOKEN) or through the Microsoft 365 MCP
                 connector via `claude -p` (plan B when the tenant blocks Graph Explorer).
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from .models import Event, Issue, JiraChange, Message
from .window import Window

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
CHAT_EXPORT = ROOT / "_local-only" / "chats-export.json"
JQL_OPEN = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
GRAPH = "https://graph.microsoft.com/v1.0"
MAX_ITEMS = 50


class SourceBlocked(Exception):
    """The source denied access (401/403): a tenant/permission limit, not a bug."""


class MissingConfig(Exception):
    """A required credential/variable is not set in .env."""


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise MissingConfig(name)
    return value


class Sources(Protocol):
    def issues(self) -> list[Issue]: ...
    def changes(self, w: Window) -> list[JiraChange]: ...
    def events(self, start: date, end: date) -> list[Event]: ...
    def mails(self, w: Window) -> list[Message]: ...
    def chats(self, w: Window) -> list[Message]: ...
    def chats_export(self, w: Window) -> tuple[list[Message], str]: ...
    def owner(self) -> list[str]: ...


def owner_from_env() -> list[str]:
    """DIGEST_OWNER="Juan Cruz Casella|Juan Casella": names the mailbox owner appears with."""
    return [n.strip() for n in os.getenv("DIGEST_OWNER", "").split("|") if n.strip()]


def is_owner(name: str, owner: list[str]) -> bool:
    n = (name or "").strip().lower()
    return bool(n) and any(n == o.lower() or o.lower() in n for o in owner)


# --- time helpers -------------------------------------------------------------------------

def local_tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("DIGEST_TZ", "America/Argentina/Buenos_Aires"))


def to_local_naive(s: str) -> datetime:
    """ISO 8601 (with Z, ±HH:MM or ±HHMM offsets, or naive=already local) → naive local time."""
    s = s.strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # Graph sends 7 fractional digits
    dt = datetime.fromisoformat(s)
    return dt.astimezone(local_tz()).replace(tzinfo=None) if dt.tzinfo else dt


def to_utc_iso(local_naive: datetime) -> str:
    return local_naive.replace(tzinfo=local_tz()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- static (fixtures / evals) ------------------------------------------------------------

def _at(day: date, hm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hm, "%H:%M").time())


def parse_issue(d: dict) -> Issue:
    return Issue(d["key"], d["summary"], d["status"], d.get("priority") or "Medium",
                 date.fromisoformat(d["due"]) if d.get("due") else None, datetime.fromisoformat(d["updated"]))


def parse_mail(d: dict, day: date) -> Message:
    return Message(d["id"], "mail", d.get("from", ""), d.get("subject", ""), _at(day, d["time"]), d.get("preview", ""))


def parse_chat(d: dict, day: date) -> Message:
    return Message(d["id"], "chat", d.get("from", ""), d.get("chat", ""), _at(day, d["time"]), d.get("text", ""))


def _fixture(name: str):
    path = FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def fixture_data() -> dict:
    return {
        "issues": _fixture("issues.json"), "events": _fixture("events.json"),
        "events_window": _fixture("events_window.json"), "changes": _fixture("changes.json"),
        "mails": _fixture("mails.json"), "chats": _fixture("chats.json"),
    }


class StaticSources:
    """Items with only a time ("HH:MM") are placed on the plan day (events) or the window start."""

    def __init__(self, data: dict, day: date, window: Window):
        self.data, self.day, self.w = data, day, window
        self.blocked = set(data.get("blocked", []))
        self.failing = set(data.get("failing", []))

    def _guard(self, name: str) -> None:
        if name in self.blocked:
            raise SourceBlocked(f"{name}: acceso denegado (403) por el tenant")
        if name in self.failing:
            raise RuntimeError(f"{name}: la fuente no respondió (simulado)")

    def issues(self) -> list[Issue]:
        self._guard("jira")
        return [parse_issue(d) for d in self.data.get("issues", [])]

    def changes(self, w: Window) -> list[JiraChange]:
        self._guard("jira")
        return [JiraChange(d["key"], d.get("summary", ""), _at(w.start, d["time"]), d["kind"], d.get("detail", ""),
                           d.get("author", "")) for d in self.data.get("changes", [])]

    def events(self, start: date, end: date) -> list[Event]:
        self._guard("calendar")
        out = []
        for key, day in (("events", self.day), ("events_window", self.w.start)):
            if start <= day <= end:
                out += [Event(d["subject"], _at(day, d["start"]), _at(day, d["end"]), d.get("id", "")) for d in self.data.get(key, [])]
        return out

    def mails(self, w: Window) -> list[Message]:
        self._guard("mails")
        return [parse_mail(d, w.start) for d in self.data.get("mails", [])]

    def chats(self, w: Window) -> list[Message]:
        self._guard("chats")
        return [parse_chat(d, w.start) for d in self.data.get("chats", [])]

    def chats_export(self, w: Window) -> tuple[list[Message], str]:
        rows = self.data.get("chats_export", _fixture("chats.json"))
        return [parse_chat(d, w.start) for d in rows], "export de ejemplo (fixtures/chats.json)"

    def owner(self) -> list[str]:
        return list(self.data.get("owner", ["Ana Ejemplo"]))


def fixture_issues() -> list[Issue]:
    return [parse_issue(d) for d in _fixture("issues.json")]


def fixture_events(day: date) -> list[Event]:
    return [Event(d["subject"], _at(day, d["start"]), _at(day, d["end"])) for d in _fixture("events.json")]


# --- Jira Cloud REST ----------------------------------------------------------------------

def _jira():
    return _env("JIRA_BASE_URL").rstrip("/"), (_env("JIRA_EMAIL"), _env("JIRA_API_TOKEN"))


def _jira_get(path: str, params: dict) -> dict:
    base, auth = _jira()
    r = httpx.get(f"{base}{path}", params=params, auth=auth, timeout=30)
    if r.status_code in (401, 403):
        raise SourceBlocked(f"jira: {r.status_code} (credenciales vencidas o sin permiso)")
    r.raise_for_status()
    return r.json()


def jira_issues() -> list[Issue]:
    base, _ = _jira()
    data = _jira_get("/rest/api/3/search/jql", {"jql": JQL_OPEN, "fields": "summary,status,priority,duedate,updated",
                                                "maxResults": MAX_ITEMS})
    out = []
    for it in data["issues"]:
        f = it["fields"]
        out.append(Issue(
            key=it["key"], summary=f["summary"], status=f["status"]["name"],
            priority=(f.get("priority") or {}).get("name", "Medium"),
            due=date.fromisoformat(f["duedate"]) if f.get("duedate") else None,
            updated=to_local_naive(f["updated"]), url=f"{base}/browse/{it['key']}",
        ))
    return out


def parse_jira_changes(data: dict, w: Window) -> list[JiraChange]:
    """Status transitions and new comments inside the window. Comment bodies are never copied."""
    out = []
    for it in data.get("issues", []):
        key, f = it["key"], it.get("fields", {})
        summary = f.get("summary", "")
        for h in (it.get("changelog") or {}).get("histories", []):
            at = to_local_naive(h["created"])
            if not w.contains(at):
                continue
            who = (h.get("author") or {}).get("displayName", "")
            for item in h.get("items", []):
                if item.get("field") == "status":
                    out.append(JiraChange(key, summary, at, "transition",
                                          f"{item.get('fromString')} → {item.get('toString')}", who))
        for c in ((f.get("comment") or {}).get("comments") or []):
            at = to_local_naive(c["created"])
            if w.contains(at):
                out.append(JiraChange(key, summary, at, "comment", "nuevo comentario",
                                      (c.get("author") or {}).get("displayName", "")))
    return sorted(out, key=lambda c: c.at)


def jira_changes(w: Window) -> list[JiraChange]:
    jql = (f'(assignee = currentUser() OR assignee WAS currentUser() OR reporter = currentUser()) '
           f'AND updated >= "{w.start:%Y-%m-%d}" AND updated < "{w.end + timedelta(days=1):%Y-%m-%d}"')
    data = _jira_get("/rest/api/3/search/jql", {"jql": jql, "fields": "summary,comment", "expand": "changelog",
                                                "maxResults": MAX_ITEMS})
    return parse_jira_changes(data, w)


# --- Microsoft Graph (needs GRAPH_ACCESS_TOKEN) --------------------------------------------

def _graph_get(url: str, params: dict | None = None, pages: int = 3) -> list[dict]:
    tz = os.getenv("GRAPH_TIMEZONE", "Argentina Standard Time")
    headers = {"Authorization": f"Bearer {_env('GRAPH_ACCESS_TOKEN')}", "Prefer": f'outlook.timezone="{tz}"'}
    out: list[dict] = []
    for _ in range(pages):
        r = httpx.get(url, params=params, headers=headers, timeout=30)
        if r.status_code in (401, 403):
            try:
                code = (r.json().get("error") or {}).get("code", "")
            except ValueError:  # non-JSON body (proxy/HTML): still a permission problem
                code = ""
            raise SourceBlocked(f"graph: {r.status_code} {code} (token vencido o permiso no concedido)")
        r.raise_for_status()
        d = r.json()
        out += d.get("value", [])
        url, params = d.get("@odata.nextLink"), None
        if not url or len(out) >= MAX_ITEMS:
            break
    return out[:MAX_ITEMS]


def parse_graph_event(e: dict) -> Event:
    return Event(e.get("subject") or "(sin asunto)", to_local_naive(e["start"]["dateTime"]),
                 to_local_naive(e["end"]["dateTime"]), e.get("id", ""))


def graph_events(start: date, end: date) -> list[Event]:
    rows = _graph_get(f"{GRAPH}/me/calendarView", {
        "startDateTime": f"{start}T00:00:00", "endDateTime": f"{end + timedelta(days=1)}T00:00:00",
        "$select": "id,subject,start,end,isCancelled", "$top": MAX_ITEMS})
    return [parse_graph_event(e) for e in rows if not e.get("isCancelled")]


def parse_graph_mail(m: dict, folder_field: str) -> Message:
    sender = ((m.get("from") or {}).get("emailAddress") or {}).get("name", "")
    return Message(m["id"], "mail", sender, m.get("subject") or "", to_local_naive(m[folder_field]), m.get("bodyPreview") or "")


def graph_mails(w: Window) -> list[Message]:
    s, e = to_utc_iso(w.start_dt), to_utc_iso(w.end_dt)
    out = []
    for path, fld in (("/me/mailFolders/inbox/messages", "receivedDateTime"),
                      ("/me/mailFolders/sentitems/messages", "sentDateTime")):
        rows = _graph_get(f"{GRAPH}{path}", {
            "$filter": f"{fld} ge {s} and {fld} lt {e}", "$orderby": f"{fld} desc",
            "$select": f"id,subject,from,{fld},bodyPreview", "$top": 25})
        out += [parse_graph_mail(m, fld) for m in rows]
    return out


_HTML = re.compile(r"<[^>]+>")


def parse_graph_chat_message(m: dict, chat_name: str) -> Message | None:
    if m.get("messageType") != "message" or m.get("deletedDateTime"):
        return None
    sender = ((m.get("from") or {}).get("user") or {}).get("displayName", "")
    text = _HTML.sub(" ", (m.get("body") or {}).get("content") or "")
    return Message(m["id"], "chat", sender, chat_name, to_local_naive(m["createdDateTime"]), text)


def graph_chats(w: Window) -> list[Message]:
    chats = _graph_get(f"{GRAPH}/me/chats", {"$expand": "lastMessagePreview", "$top": 50}, pages=1)
    out: list[Message] = []
    for c in chats:
        last = (c.get("lastMessagePreview") or {}).get("createdDateTime")
        if not last or to_local_naive(last) < w.start_dt:
            continue
        name = c.get("topic") or ("chat 1:1" if c.get("chatType") == "oneOnOne" else "chat grupal")
        for m in _graph_get(f"{GRAPH}/me/chats/{c['id']}/messages", {"$top": 50}, pages=1):
            msg = parse_graph_chat_message(m, name)
            if msg and w.contains(msg.sent):
                out.append(msg)
        if len(out) >= MAX_ITEMS:
            break
    return out[:MAX_ITEMS]


# --- real sources --------------------------------------------------------------------------

def load_chat_export(path: Path, w: Window) -> list[Message]:
    """Plan B for chats: a JSON export [{id, from, chat, time|sent, text}] in _local-only/."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for d in rows:
        sent = to_local_naive(d["sent"]) if d.get("sent") else _at(w.start, d["time"])
        if w.contains(sent):
            out.append(Message(d["id"], "chat", d.get("from", ""), d.get("chat", ""), sent, d.get("text", "")))
    return out


class RealSources:
    def __init__(self, m365: str = "auto", tracer=None):
        has_token = bool(os.getenv("GRAPH_ACCESS_TOKEN"))
        if m365 == "auto":
            m365 = "graph" if has_token else "mcp"
        if m365 == "graph" and not has_token:
            raise ValueError("--fuentes-m365 graph requiere GRAPH_ACCESS_TOKEN en .env")
        self.m365, self._tracer, self._mcp_client = m365, tracer, None

    @property
    def _mcp(self):
        """Built lazily: Jira must keep working even if the `claude` binary is missing."""
        if self._mcp_client is None:
            from .m365_mcp import M365ViaMCP

            self._mcp_client = M365ViaMCP(self._tracer)
        return self._mcp_client

    def issues(self) -> list[Issue]:
        return jira_issues()

    def changes(self, w: Window) -> list[JiraChange]:
        return jira_changes(w)

    def events(self, start: date, end: date) -> list[Event]:
        return graph_events(start, end) if self.m365 == "graph" else self._mcp.events(start, end)

    def mails(self, w: Window) -> list[Message]:
        return graph_mails(w) if self.m365 == "graph" else self._mcp.mails(w)

    def chats(self, w: Window) -> list[Message]:
        return graph_chats(w) if self.m365 == "graph" else self._mcp.chats(w)

    def owner(self) -> list[str]:
        names = owner_from_env()
        if names:
            return names
        me = _jira_get("/rest/api/3/myself", {})
        return [n for n in (me.get("displayName"), me.get("emailAddress")) if n]

    def chats_export(self, w: Window) -> tuple[list[Message], str]:
        if CHAT_EXPORT.exists():
            return load_chat_export(CHAT_EXPORT, w), "export local (_local-only/chats-export.json)"
        return [], "sin export de chats"
