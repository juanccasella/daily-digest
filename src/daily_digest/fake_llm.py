"""Deterministic simulated model for offline evals.

Default behaviour is a well-behaved model (never obeys injected instructions). A golden case can
script per-agent answers to simulate a model that invents citations, breaks rules or "obeys" an
injection: the point of those evals is that the code-side critic catches it anyway.
"""

import json
import re
from datetime import date, datetime

from .agents import heuristic_links
from .heuristic import heuristic_plan
from .llm import Completion
from .models import Claim, Event, Goal, Issue
from .security import looks_like_injection

_MSG = re.compile(r'<mensaje id="([^"]+)" canal="(\w+)"[^>]*>\n│ de: (.*)\n│ asunto: (.*)\n│ ?(.*)\n</mensaje>')


class FakeLLM:
    provider = "fake"
    model = "fake-deterministic"

    def __init__(self, script: dict[str, list] | None = None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, agent: str, system: str, user: str) -> Completion:
        self.calls.append((agent, system, user))
        queue = self.script.get(agent)
        if queue:
            ans = queue.pop(0)
            text = ans if isinstance(ans, str) else json.dumps(ans, ensure_ascii=False)
        else:
            text = json.dumps(getattr(self, f"_{agent}")(user), ensure_ascii=False)
        return Completion(text, self.model, len(system + user) // 4, len(text) // 4, 0.0)

    @staticmethod
    def _payload(user: str) -> dict:
        return json.JSONDecoder().raw_decode(user)[0]

    def _reader(self, user: str) -> dict:
        claims = []
        for cid, channel, sender, subject, body in _MSG.findall(user):
            if looks_like_injection(f"{subject} {body}"):
                claims.append({"text": f"{cid} contiene instrucciones dirigidas a un asistente (posible inyección).", "cites": [cid]})
            elif subject.strip() or body.strip():
                what = (body.strip() if channel == "chat" else subject.strip() or body.strip())[:160]
                claims.append({"text": f"{'Mail' if channel == 'mail' else 'Chat'} de {sender.strip()}: {what}", "cites": [cid]})
        return {"claims": claims[:10]}

    def _linker(self, user: str) -> dict:
        p = self._payload(user)
        goals = [Goal(g["id"], g["texto"]) for g in p["objetivos"]]
        adv = [Claim(c["text"], tuple(c["cites"])) for c in p["avanzado"]]
        return {"links": [{"goal": ln.goal, "text": ln.text, "cites": list(ln.cites)} for ln in heuristic_links(goals, adv)]}

    def _planner(self, user: str) -> dict:
        p = self._payload(user)
        day = date.fromisoformat(p["hoy"])
        issues = [Issue(t["key"], t["summary"], t["status"], t["priority"],
                        date.fromisoformat(t["due"]) if t["due"] else None, datetime.fromisoformat(t["updated"]))
                  for t in p["tickets"]]
        at = lambda hm: datetime.combine(day, datetime.strptime(hm, "%H:%M").time())  # noqa: E731
        events = [Event(e["subject"], at(e["start"]), at(e["end"])) for e in p["reuniones"]]
        plan = heuristic_plan(issues, events, day)
        return {"plan": [{"key": x.key, "reason": x.reason, "start": f"{x.start:%H:%M}", "minutes": x.minutes} for x in plan]}
