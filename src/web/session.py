"""ChatSession — per-session conversation engine for the web UI.

Mirrors the terminal client's behaviour (intent routing, conversational approval
for single + multi-step writes, no-op detection, RCA recommendation follow-ups,
session-change recap with approval-history fallback) but is:

  * stateful PER SESSION (each browser tab gets its own ChatSession), and
  * returns STRUCTURED data instead of printing, so the browser can render
    approval buttons, recommended-action chips, and status badges.

Public API:
    session = ChatSession()
    result  = await session.send("how many active customers?")

`result` shape:
    {
      "reply": str,                 # assistant text (may contain newlines / simple md)
      "kind":  "answer"|"pending"|"applied"|"no_change"|"rejected"|"error",
      "pending": {"label": str, "steps": int} | None,   # present => show Approve/Cancel
      "actions": [str, ...] | None,                     # RCA recommendations => chips
    }
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from openai import AsyncOpenAI

_AFFIRMATIVE = {"yes", "y", "approve", "approved", "confirm", "ok", "okay",
                "go ahead", "proceed", "do it", "sure"}
_NEGATIVE = {"no", "n", "cancel", "reject", "stop", "abort", "nevermind"}

_ORDINALS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "fifth": 5, "5th": 5,
}
_RECO_REF = (
    "recommend", "recommendation", "suggested", "suggestion", "that fix",
    "those fixes", "the fix", "remediation", "apply it", "apply that",
    "apply them", "do that", "do it", "go ahead with", "implement",
    "take that action", "action it",
)

_CHANGE_NOUNS = (r"change|changes|insert|inserts|update|updates|edit|edits|"
                 r"modification|modifications")
_CHANGE_RECAP = re.compile(
    r"(what|which|show|list|tell|give|display).{0,40}"
    r"(you|i|we).{0,30}"
    r"(chang|creat|insert|add\b|updat|delet|modif|do\b|did|done|appl|made|edit)"
    rf"|(show|list|see|display|tell|give).{{0,30}}\b({_CHANGE_NOUNS})\b"
    rf"|\b(what|which)\b.{{0,25}}\b({_CHANGE_NOUNS})\b"
    r"|\b(recent|latest|last|session)\b.{0,20}\b(change|insert|update|edit|action)s?\b",
    re.IGNORECASE,
)

_HISTORY_MAX = 12

_PRESENTER_SYSTEM = (
    "You are a helpful Finance & Billing assistant for the company TCL. "
    "The user asked a question and a backend returned structured JSON data. "
    "Answer the user directly and conversationally in plain English. "
    "Be concise and specific - cite the actual numbers, names, codes and statuses "
    "from the data. Use short sentences or a small bullet list when listing items. "
    "When listing service requests / tickets, ALWAYS include, for each one, who it "
    "is assigned to (show 'Unassigned' when there is no assignee) and who raised it "
    "(the 'raised by' person — do not add a separate 'created by' line), in addition "
    "to the description, priority and status. "
    "Never mention JSON, tools, agents, routing, or internal field names. "
    "If the data is empty or null, say that no matching records were found."
)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class ChatSession:
    """One conversation. Not safe for concurrent calls — guarded by an internal
    lock so overlapping requests from the same tab are serialised."""

    def __init__(self, approver: str = "web_user") -> None:
        self.approver = approver
        self.history: list[dict] = []
        self.session_changes: list[dict] = []
        self.last_context: dict | None = None
        # pending = {"kind":"single","request_id","desc","leaf"} OR
        #           {"kind":"batch","label","steps":[{request_id,description}]}
        self.pending: dict | None = None
        self._lock = asyncio.Lock()

    # ── public ────────────────────────────────────────────────────────────────

    async def send(self, text: str) -> dict:
        async with self._lock:
            try:
                return await self._handle((text or "").strip())
            except Exception as exc:  # noqa: BLE001 — never 500 the UI
                return self._out(f"Sorry — something went wrong: {exc}", "error")

    # ── result builder ──────────────────────────────────────────────────────────

    def _out(self, reply: str, kind: str, *, actions=None) -> dict:
        pending = None
        if self.pending:
            if self.pending["kind"] == "batch":
                pending = {"label": self.pending["label"],
                           "steps": len(self.pending["steps"])}
            else:
                pending = {"label": self.pending.get("desc", "this change"),
                           "steps": 1}
        return {"reply": reply, "kind": kind, "pending": pending,
                "actions": actions or None}

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": assistant_text})
        if len(self.history) > _HISTORY_MAX * 2:
            del self.history[: len(self.history) - _HISTORY_MAX * 2]

    def _record_change(self, request_id, summary: str) -> None:
        self.session_changes.append({"request_id": request_id,
                                     "summary": summary or "change applied"})

    # ── main dispatch ───────────────────────────────────────────────────────────

    async def _handle(self, text: str) -> dict:
        if not text:
            return self._out("", "answer")
        low = text.lower()

        # 1) A change is awaiting approval → interpret yes/no.
        if self.pending is not None:
            if low in _AFFIRMATIVE:
                return await self._resolve(True)
            if low in _NEGATIVE:
                return await self._resolve(False)
            n = (len(self.pending["steps"]) if self.pending["kind"] == "batch" else 1)
            label = "all steps" if n > 1 else "this change"
            return self._out(
                f"You have {n} change(s) awaiting approval. Use **Approve** to apply "
                f"{label} or **Cancel** to discard.", "pending")

        # 2) "What did you change/create?" → session log, else approval history.
        if _CHANGE_RECAP.search(text):
            recap = await self._change_recap()
            self._remember(text, recap)
            return self._out(recap, "answer")

        # 3) Natural-language request → intent router (with follow-up rewriting).
        from src.agents.intent_router import run as router_run
        routed = self._maybe_followup(text) or text
        payload = await router_run(routed)

        if not payload.get("success", True):
            msg = f"Sorry — {payload.get('message', 'something went wrong')}."
            return self._out(msg, "error")

        kind, leaf = self._find_write(payload)

        steps = self._onboarding_steps(leaf)
        if steps:
            cust = leaf.get("customer_number")
            acct = leaf.get("account_number")
            lines = [f"I've prepared a {len(steps)}-step onboarding"
                     + (f" for {cust}" if cust else "")
                     + (f" (account {acct})" if acct else "") + ":"]
            for i, s in enumerate(steps, 1):
                lines.append(f"{i}. {s['description']} (request #{s['request_id']})")
            lines.append("Approve to apply all steps, or Cancel to discard.")
            self.pending = {"kind": "batch",
                            "label": f"onboarding{(' for ' + cust) if cust else ''}",
                            "steps": steps}
            reply = "\n".join(lines)
            self._remember(text, reply)
            return self._out(reply, "pending")

        if kind == "no_change":
            msg = leaf.get("message", "No change needed.")
            self._remember(text, msg)
            return self._out(msg, "no_change")

        if kind == "pending":
            reply = self._confirmation_text(leaf)
            desc = leaf.get("summary") or leaf.get("action") or "change"
            self.pending = {"kind": "single", "request_id": leaf["request_id"],
                            "desc": desc, "leaf": leaf}
            self._remember(text, reply)
            return self._out(reply, "pending")

        # Read / answer
        self._capture_rca_context(leaf)
        answer = await self._say(routed, leaf)
        actions = leaf.get("recommended_actions") if isinstance(leaf, dict) else None
        if not (isinstance(actions, list) and actions):
            actions = None
        self._remember(text, answer)
        return self._out(answer, "answer", actions=actions)

    # ── approval resolution ─────────────────────────────────────────────────────

    async def _resolve(self, affirm: bool) -> dict:
        from src.tools.approval import approve_request, reject_request
        pend = self.pending
        self.pending = None

        if pend["kind"] == "batch":
            steps = pend["steps"]
            label = pend["label"]
            if not affirm:
                for st in steps:
                    if st.get("request_id"):
                        await reject_request(st["request_id"], self.approver,
                                             "cancelled in web UI")
                return self._out(
                    f"Cancelled — no changes were made ({label}: "
                    f"{len(steps)} steps rejected).", "rejected")
            applied, failed = 0, []
            for st in steps:
                rid = st.get("request_id")
                if not rid:
                    continue
                res = await approve_request(rid, self.approver)
                if res.get("success"):
                    applied += 1
                    self._record_change(rid, st.get("description", label))
                else:
                    failed.append(f"#{rid}: {res.get('message', res.get('error_code'))}")
            reply = f"Done — {label}: applied {applied} of {len(steps)} steps."
            if failed:
                reply += "\nFailed:\n" + "\n".join(failed)
            return self._out(reply, "applied")

        # single
        rid = pend["request_id"]
        leaf = pend.get("leaf", {})
        if not affirm:
            await reject_request(rid, self.approver, "cancelled in web UI")
            return self._out(
                f"Cancelled — no changes were made (request #{rid} rejected).",
                "rejected")
        res = await approve_request(rid, self.approver)
        if not res.get("success"):
            return self._out(
                f"Could not apply it: {res.get('message', res.get('error_code'))}",
                "error")
        change = res.get("change_summary")
        if not change:
            cur, req = leaf.get("current_value"), leaf.get("requested_value")
            rows = res.get("rows_affected")
            if cur is not None and req is not None:
                change = f"changed from '{cur}' to '{req}'"
            elif rows is not None:
                change = f"{rows} row{'s' if rows != 1 else ''} changed"
        pq = (res.get("dml_result") or {}).get("post_query_result") or {}
        details = [d for d in (change,) if d]
        if pq:
            details.append(", ".join(f"{k}={v}" for k, v in pq.items()))
        tail = (" — " + "; ".join(details)) if details else ""
        self._record_change(rid, change or pend.get("desc"))
        return self._out(f"Done — approved and applied (request #{rid}).{tail}",
                         "applied")

    # ── presenter ───────────────────────────────────────────────────────────────

    async def _say(self, question: str, data: dict) -> str:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        blob = json.dumps(data, default=str)
        if len(blob) > 6000:
            blob = blob[:6000] + " ...(truncated)"
        messages = [{"role": "system", "content": _PRESENTER_SYSTEM}]
        messages.extend(self.history[-_HISTORY_MAX:])
        messages.append({"role": "user",
                         "content": f"Question: {question}\n\nData returned:\n{blob}"})
        try:
            resp = await _client().chat.completions.create(model=model, messages=messages)
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            return f"(could not summarize: {exc})\n{blob[:800]}"

    # ── result navigation (same logic as the terminal client) ───────────────────

    @staticmethod
    def _drill(payload: dict) -> dict:
        node = payload
        seen = 0
        while isinstance(node, dict) and isinstance(node.get("result"), dict) and seen < 5:
            node = node["result"]
            seen += 1
        return node

    def _find_write(self, payload: dict):
        leaf = self._drill(payload)
        if isinstance(leaf, dict):
            details = leaf.get("details")
            if isinstance(details, dict):
                leaf = {**details, **leaf}
            if leaf.get("no_change") or leaf.get("status") == "NO_CHANGE":
                return "no_change", leaf
            if leaf.get("request_id") and leaf.get("status") == "PENDING":
                return "pending", leaf
        return None, leaf

    @staticmethod
    def _confirmation_text(leaf: dict) -> str:
        action = (leaf.get("action") or leaf.get("procedure_name") or "this change")
        action = str(action).replace("_", " ")
        cur, req = leaf.get("current_value"), leaf.get("requested_value")
        if cur is not None and req is not None:
            body = f"This will change it from '{cur}' to '{req}'."
        else:
            body = leaf.get("summary") or f"This will perform: {action}."
        warn = leaf.get("warning")
        extra = f"\n⚠️ {warn}" if warn else ""
        return f"I've prepared this change ({action}). {body}{extra}"

    @staticmethod
    def _onboarding_steps(leaf: dict):
        if not isinstance(leaf, dict):
            return None
        steps = leaf.get("steps")
        if not (isinstance(steps, list) and leaf.get("total_steps")):
            return None
        pending = [{"request_id": s.get("request_id"),
                    "description": s.get("description", "step")}
                   for s in steps if s.get("request_id") and s.get("status") == "PENDING"]
        return pending or None

    # ── conversation context (RCA + follow-ups) ─────────────────────────────────

    def _capture_rca_context(self, leaf: dict) -> None:
        if not isinstance(leaf, dict):
            return
        actions = leaf.get("recommended_actions")
        if isinstance(actions, list) and actions:
            self.last_context = {
                "customer_number": leaf.get("customer_number"),
                "recommended_actions": [str(a) for a in actions],
                "rca_summary": leaf.get("rca_summary", ""),
            }

    def _maybe_followup(self, text: str) -> str | None:
        low = text.lower()
        reco = self._reco_followup_request(low)
        if reco:
            return reco
        if self.last_context and self.last_context.get("customer_number"):
            if re.search(r"\b(he|him|his|she|her|they|them|their|that customer|this customer)\b", low):
                return f"{text} (regarding customer {self.last_context['customer_number']})"
        return None

    def _reco_followup_request(self, low: str) -> str | None:
        if not self.last_context or not any(k in low for k in _RECO_REF):
            return None
        actions = self.last_context.get("recommended_actions") or []
        if not actions:
            return None
        cust = self.last_context.get("customer_number") or "the customer"
        summary = (self.last_context.get("rca_summary") or "")[:400]
        pick = self._pick_action_index(low, len(actions))
        if pick == 0:
            chosen = "; ".join(actions)
        elif pick is None:
            chosen = actions[0]
        else:
            chosen = actions[pick - 1]
        return (f"For customer {cust}, carry out this recommended remediation action "
                f"from the earlier root-cause analysis: \"{chosen}\". "
                f"Context for the analysis: {summary}")

    @staticmethod
    def _pick_action_index(low: str, n: int):
        if "all" in low or "every" in low or "them all" in low:
            return 0
        m = re.search(r"(?:action|recommendation|option|step|#)\s*(\d+)", low)
        if m:
            idx = int(m.group(1))
            return idx if 1 <= idx <= n else None
        for word, idx in _ORDINALS.items():
            if re.search(rf"\b{word}\b", low) and idx <= n:
                return idx
        return None

    # ── change recap (session first, then approval history) ─────────────────────

    def _format_session_changes(self) -> str:
        if not self.session_changes:
            return "I haven't applied any changes in this session yet."
        lines = ["Here's what I've changed in this session (most recent first):"]
        for i, ch in enumerate(reversed(self.session_changes), 1):
            rid = ch.get("request_id")
            lines.append(f"{i}. {ch['summary']}" + (f" (request #{rid})" if rid else ""))
        return "\n".join(lines)

    async def _change_recap(self) -> str:
        if self.session_changes:
            return self._format_session_changes()
        try:
            from src.tools.approval import get_recent_changes
            res = await get_recent_changes(10)
        except Exception as exc:  # noqa: BLE001
            res = {"success": False, "message": str(exc)}
        rows = (res or {}).get("data") or []
        if not rows:
            return ("I haven't applied any changes in this session yet, and I don't "
                    "see any recently approved changes in the history.")
        lines = ["I haven't applied changes in THIS session, but here are the most "
                 "recently approved changes (from the approval history):"]
        for i, ch in enumerate(rows, 1):
            tail = ""
            if ch.get("approved_by"):
                tail += f" — by {ch['approved_by']}"
            if ch.get("approved_dtm"):
                tail += f" on {ch['approved_dtm']}"
            lines.append(f"{i}. {ch['summary']} (request #{ch.get('request_id')}){tail}")
        return "\n".join(lines)
