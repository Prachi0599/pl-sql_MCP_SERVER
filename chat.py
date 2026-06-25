"""
Interactive chat client for the TCL Finance & Billing MCP Server.

Talk to the server in plain English and get plain-English answers. Every line you
type is sent to the intent_router agent — the same top-level entry point a real
MCP client (e.g. Claude Desktop) would reach — which classifies it as READ or
WRITE and routes it. This client then turns the structured result into a normal
conversational reply (no JSON, no routing internals) and, for write requests,
walks you through a human-friendly approval step.

Run from the project root:

    python chat.py

Requires a populated .env (DB_USER, DB_PASSWORD, DB_CONNECT_STRING, OPENAI_API_KEY).

How writes work here:
  * You ask for a change (e.g. "set account ACC000123 to INACTIVE").
  * If it is already in that state, you are simply told "already INACTIVE - no
    change needed" and nothing is staged.
  * Otherwise you see exactly what will change (from X to Y) and are asked to
    confirm. Reply "yes" to approve and apply it, or "no" to cancel.

Slash commands (optional shortcuts):
    /help                 show examples and commands
    /raw                  toggle full raw-JSON output on/off (for debugging)
    /pending              list all PENDING approval requests
    /approve <id> <user>  approve a request directly
    /reject  <id> <user>  reject a request directly
    /quit  |  /exit       leave the chat
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()

# Windows terminals default to cp1252; force UTF-8 so output never crashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

RAW_MODE = False
# When a single write is staged, holds (request_id, approver, human_description,
# leaf) until the user confirms or cancels it.
PENDING_APPROVAL: tuple | None = None
# When a MULTI-STEP write is staged (e.g. onboarding), holds a dict
# {"label": str, "steps": [{"request_id", "description"}, ...]} so a single
# "yes" approves and applies every step in order.
PENDING_BATCH: dict | None = None
_APPROVER = "chat_user"

# ── Conversation memory ───────────────────────────────────────────────────────
# Rolling chat history (so natural follow-ups read in context), the last "rich"
# result (e.g. an RCA), and a log of changes APPLIED in this session so the user
# can ask "what did you change/create?" and get exactly that — not a DB-wide dump.
CHAT_HISTORY: list[dict] = []
_HISTORY_MAX = 12            # keep the last N turns for the presenter
LAST_CONTEXT: dict | None = None   # {"customer_number","recommended_actions","rca_summary"}
SESSION_CHANGES: list[dict] = []   # [{"request_id","summary","action"}], newest last

# Questions that mean "tell me what YOU changed/created/inserted in this session".
# Broad on purpose: "show me what you have inserted", "show me the changes",
# "what did you create", "list recent updates" should all hit the session log
# rather than the LLM router (which previously dumped DB-wide / mis-routed rows).
_CHANGE_RECAP = re.compile(
    r"(what|which|show|list|tell|give|display).{0,40}"
    r"(you|i|we).{0,30}"
    r"(chang|creat|insert|add\b|updat|delet|modif|do\b|did|done|appl|made|edit)"
    r"|(show|list|see|display|tell|give).{0,30}"
    r"\b(change|changes|insert|inserts|update|updates|edit|edits|"
    r"modification|modifications)\b"
    r"|\b(recent|latest|last|session)\b.{0,20}\b(change|insert|update|edit|action)s?\b",
    re.IGNORECASE,
)

_AFFIRMATIVE = {"yes", "y", "approve", "approved", "confirm", "ok", "okay",
                "go ahead", "proceed", "do it", "sure"}
_NEGATIVE = {"no", "n", "cancel", "reject", "stop", "abort", "nevermind"}

# Ordinal words only (bare cardinals like "one" are excluded — "the second one"
# must resolve to 2, not 1).
_ORDINALS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
}
# Phrases that mean "act on the recommendation you just gave me".
_RECO_REF = (
    "recommend", "recommendation", "suggested", "suggestion",
    "that fix", "those fixes", "the fix", "remediation",
    "apply it", "apply that", "apply them", "do that", "do it",
    "go ahead with", "implement", "take that action", "action it",
)

EXAMPLES = """
Just ask in plain English - examples:

  Questions (READ)
    * How many active customers do we have?
    * Show me the monthly revenue for the last 6 months
    * List all PL/SQL packages in the schema
    * What are the top 5 accounts by usage this month?
    * Investigate billing and usage issues for customer CUST000122
    * Give me an executive revenue summary

  Changes (WRITE - you'll be asked to confirm before anything is applied)
    * Set account ACC000123 status to INACTIVE
    * Create a new currency GBP called British Pound
    * Apply a $250 CREDIT adjustment to invoice INV00000123 for account ACC000123
    * Run the monthly billing for 2026-06
"""


# ── OpenAI presenter ────────────────────────────────────────────────────────

def _client():
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


_PRESENTER_SYSTEM = (
    "You are a helpful Finance & Billing assistant for the company TCL. "
    "The user asked a question and a backend returned structured JSON data. "
    "Answer the user directly and conversationally in plain English. "
    "Be concise and specific - cite the actual numbers, names, codes and statuses "
    "from the data. Use short sentences or a small bullet list when listing items. "
    "When listing service requests / tickets, ALWAYS include, for each one, who it "
    "is assigned to (show 'Unassigned' when there is no assignee) and who raised/"
    "created it, in addition to the description, priority and status. "
    "Never mention JSON, tools, agents, routing, or internal field names. "
    "If the data is empty or null, say that no matching records were found."
)


async def _say(question: str, data: dict) -> str:
    """Turn a structured result into a natural-language answer.

    Recent conversation history is included so the model can resolve follow-ups
    ("what about his accounts?", "and the second one?") in context."""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    blob = json.dumps(data, default=str)
    if len(blob) > 6000:
        blob = blob[:6000] + " ...(truncated)"
    messages = [{"role": "system", "content": _PRESENTER_SYSTEM}]
    # Replay a trimmed history so the reply stays on-thread.
    messages.extend(CHAT_HISTORY[-_HISTORY_MAX:])
    messages.append({"role": "user",
                     "content": f"Question: {question}\n\nData returned:\n{blob}"})
    try:
        resp = await _client().chat.completions.create(
            model=model,
            messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # fall back to a compact dump
        return f"(could not summarize: {exc})\n{blob[:800]}"


# ── result navigation ─────────────────────────────────────────────────────────

def _drill(payload: dict) -> dict:
    """Follow nested router/master/sub-agent envelopes down to the leaf result."""
    node = payload
    seen = 0
    while isinstance(node, dict) and isinstance(node.get("result"), dict) and seen < 5:
        node = node["result"]
        seen += 1
    return node


def _find_write(payload: dict):
    """If this response represents a write, return ('no_change'|'pending', leaf).
    Otherwise return (None, leaf)."""
    leaf = _drill(payload)
    if isinstance(leaf, dict):
        # The agent's richer tool fields live under "details"; merge them up so
        # message / current_value / requested_value are always available.
        details = leaf.get("details")
        if isinstance(details, dict):
            leaf = {**details, **leaf}
        if leaf.get("no_change") or leaf.get("status") == "NO_CHANGE":
            return "no_change", leaf
        if leaf.get("request_id") and leaf.get("status") == "PENDING":
            return "pending", leaf
    return None, leaf


def _confirmation_text(leaf: dict) -> str:
    """Build a clear, human confirmation prompt for a staged change."""
    action = (leaf.get("action") or leaf.get("procedure_name") or "this change")
    action = str(action).replace("_", " ")
    cur = leaf.get("current_value")
    req = leaf.get("requested_value")
    if cur is not None and req is not None:
        body = f"This will change it from '{cur}' to '{req}'."
    else:
        body = leaf.get("summary") or f"This will perform: {action}."
    return (f"I've prepared this change ({action}). {body}\n"
            f"  Reply 'yes' to approve and apply it, or 'no' to cancel.")


# ── conversation context (RCA recommendations + follow-ups) ───────────────────

def _remember(user_text: str, assistant_text: str) -> None:
    """Append a turn to the rolling chat history (trimmed to the last N turns)."""
    CHAT_HISTORY.append({"role": "user", "content": user_text})
    CHAT_HISTORY.append({"role": "assistant", "content": assistant_text})
    if len(CHAT_HISTORY) > _HISTORY_MAX * 2:
        del CHAT_HISTORY[: len(CHAT_HISTORY) - _HISTORY_MAX * 2]


def _capture_rca_context(leaf: dict) -> None:
    """If this read result is an RCA (has recommended_actions), remember it so a
    later 'apply the recommended action' keeps the customer + actions in scope."""
    global LAST_CONTEXT
    if not isinstance(leaf, dict):
        return
    actions = leaf.get("recommended_actions")
    if isinstance(actions, list) and actions:
        LAST_CONTEXT = {
            "customer_number": leaf.get("customer_number"),
            "recommended_actions": [str(a) for a in actions],
            "rca_summary": leaf.get("rca_summary", ""),
        }


def _looks_like_reco_followup(low: str) -> bool:
    return any(kw in low for kw in _RECO_REF)


def _pick_action_index(low: str, n: int) -> int | None:
    """Resolve which recommended action the user means. Returns a 1-based index,
    0 for 'all', or None if unspecified (caller defaults to the first)."""
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


def _reco_followup_request(low: str) -> str | None:
    """Build an enriched WRITE request from a 'apply the recommendation' follow-up,
    using the remembered RCA context. Returns None if there is nothing to act on."""
    if not LAST_CONTEXT or not _looks_like_reco_followup(low):
        return None
    actions = LAST_CONTEXT.get("recommended_actions") or []
    if not actions:
        return None
    cust = LAST_CONTEXT.get("customer_number") or "the customer"
    summary = (LAST_CONTEXT.get("rca_summary") or "")[:400]

    pick = _pick_action_index(low, len(actions))
    if pick == 0:
        chosen = "; ".join(actions)
    elif pick is None:
        chosen = actions[0]
    else:
        chosen = actions[pick - 1]

    return (
        f"For customer {cust}, carry out this recommended remediation action "
        f"from the earlier root-cause analysis: \"{chosen}\". "
        f"Context for the analysis: {summary}"
    )


def _maybe_followup(stripped: str) -> str | None:
    """Rewrite a context-dependent follow-up into a self-contained request.

    1. 'apply the recommended action' → enriched WRITE request (RCA context).
    2. A pronoun-only follow-up ('what about his bills?') → same question with
       the remembered customer number appended so routing still has a subject."""
    low = stripped.lower()
    reco = _reco_followup_request(low)
    if reco:
        return reco
    if LAST_CONTEXT and LAST_CONTEXT.get("customer_number"):
        if re.search(r"\b(he|him|his|she|her|they|them|their|that customer|this customer)\b", low):
            return f"{stripped} (regarding customer {LAST_CONTEXT['customer_number']})"
    return None


# ── command + message handling ────────────────────────────────────────────────

async def _resolve_pending(affirm: bool) -> None:
    """Approve or reject the change currently awaiting confirmation."""
    global PENDING_APPROVAL
    from src.tools.approval import approve_request, reject_request
    request_id, approver, desc = PENDING_APPROVAL[0], PENDING_APPROVAL[1], PENDING_APPROVAL[2]
    leaf = PENDING_APPROVAL[3] if len(PENDING_APPROVAL) > 3 else {}
    PENDING_APPROVAL = None
    if affirm:
        res = await approve_request(request_id, approver)
        if res.get("success"):
            # The backend's change_summary already includes the row count where
            # it is meaningful, so we show it as-is (no separate row-count prefix
            # — that previously double-printed "1 row changed"). Fall back to the
            # staged leaf's before/after values only if no summary is present.
            change = res.get("change_summary")
            if not change:
                cur = leaf.get("current_value")
                req = leaf.get("requested_value")
                rows = res.get("rows_affected")
                if cur is not None and req is not None:
                    change = f"changed from '{cur}' to '{req}'"
                elif rows is not None:
                    change = f"{rows} row{'s' if rows != 1 else ''} changed"
            dml = res.get("dml_result") or {}
            pq = dml.get("post_query_result") or {}
            details = []
            if change:
                details.append(change)
            if pq:
                details.append(", ".join(f"{k}={v}" for k, v in pq.items()))
            tail = (" — " + "; ".join(details)) if details else ""
            print(f"  Done - approved and applied (request #{request_id}).{tail}")
            _record_change(request_id, change or desc, leaf.get("action"))
        else:
            print(f"  Could not apply it: {res.get('message', res.get('error_code'))}")
    else:
        await reject_request(request_id, approver, "cancelled by user in chat")
        print(f"  Cancelled - no changes were made (request #{request_id} rejected).")


def _record_change(request_id, summary: str, action: str | None = None) -> None:
    """Remember a change APPLIED in this session, for 'what did you change?' recaps."""
    SESSION_CHANGES.append({
        "request_id": request_id,
        "summary": summary or "change applied",
        "action": action or "",
    })


def _change_recap() -> str:
    """Plain-English list of what was applied in THIS session (newest first)."""
    if not SESSION_CHANGES:
        return ("I haven't applied any changes in this session yet. (Ask me to make "
                "a change and approve it, then I'll track it here.)")
    lines = ["Here's what I've changed in this session (most recent first):"]
    for i, ch in enumerate(reversed(SESSION_CHANGES), 1):
        rid = ch.get("request_id")
        rid_txt = f" (request #{rid})" if rid else ""
        lines.append(f"  {i}. {ch['summary']}{rid_txt}")
    return "\n".join(lines)


async def _resolve_batch(affirm: bool) -> None:
    """Approve (and apply) or reject every step of a staged multi-step write."""
    global PENDING_BATCH
    from src.tools.approval import approve_request, reject_request
    batch = PENDING_BATCH
    PENDING_BATCH = None
    steps = batch.get("steps", [])
    label = batch.get("label", "request")
    if affirm:
        applied, failed = 0, 0
        for st in steps:
            rid = st.get("request_id")
            if not rid:
                continue
            res = await approve_request(rid, _APPROVER)
            if res.get("success"):
                applied += 1
                _record_change(rid, f"{st.get('description', label)}",
                               st.get("description"))
            else:
                failed += 1
                print(f"    Step #{rid} failed: "
                      f"{res.get('message', res.get('error_code'))}")
        msg = f"  Done - {label}: applied {applied} of {len(steps)} steps."
        if failed:
            msg += f" {failed} failed (see above)."
        print(msg)
    else:
        for st in steps:
            rid = st.get("request_id")
            if rid:
                await reject_request(rid, _APPROVER, "cancelled by user in chat")
        print(f"  Cancelled - no changes were made ({label}: "
              f"{len(steps)} steps rejected).")


def _onboarding_steps(leaf: dict) -> list[dict] | None:
    """If the result is a multi-step onboarding bundle, return its PENDING steps."""
    if not isinstance(leaf, dict):
        return None
    steps = leaf.get("steps")
    if not (isinstance(steps, list) and leaf.get("total_steps")):
        return None
    pending = [{"request_id": s.get("request_id"),
                "description": s.get("description", "step")}
               for s in steps if s.get("request_id") and s.get("status") == "PENDING"]
    return pending or None


async def _handle(line: str) -> None:
    global RAW_MODE, PENDING_APPROVAL, PENDING_BATCH
    from src.agents.intent_router import run as router_run
    from src.tools.approval import (
        get_pending_approvals, approve_request, reject_request,
    )

    stripped = line.strip()
    if not stripped:
        return

    low = stripped.lower()

    # 1) If a change is awaiting confirmation, interpret yes/no first.
    if PENDING_BATCH is not None and not stripped.startswith("/"):
        if low in _AFFIRMATIVE:
            await _resolve_batch(affirm=True)
            return
        if low in _NEGATIVE:
            await _resolve_batch(affirm=False)
            return
        n = len(PENDING_BATCH.get("steps", []))
        print(f"  You have a {n}-step change awaiting confirmation. "
              f"Reply 'yes' to apply all or 'no' to cancel.")
        return

    if PENDING_APPROVAL is not None and not stripped.startswith("/"):
        if low in _AFFIRMATIVE:
            await _resolve_pending(affirm=True)
            return
        if low in _NEGATIVE:
            await _resolve_pending(affirm=False)
            return
        rid = PENDING_APPROVAL[0]
        print(f"  You have a change awaiting confirmation (request #{rid}). "
              f"Please reply 'yes' to apply or 'no' to cancel first.")
        return

    # 1b) "What did you change/create?" → answer from this session's change log,
    #     not a DB-wide query or a mis-routed schema dump.
    if not stripped.startswith("/") and _CHANGE_RECAP.search(stripped):
        recap = _change_recap()
        print(f"  {recap}")
        _remember(stripped, recap)
        return

    # 2) Slash commands
    if stripped in ("/quit", "/exit"):
        raise KeyboardInterrupt
    if stripped == "/help":
        print(EXAMPLES)
        return
    if stripped == "/raw":
        RAW_MODE = not RAW_MODE
        print(f"  raw mode {'ON' if RAW_MODE else 'OFF'}")
        return
    if stripped == "/pending":
        res = await get_pending_approvals()
        if RAW_MODE:
            print(json.dumps(res, indent=2, default=str))
        else:
            print(await _say("List the pending approval requests", res))
        return
    if stripped.startswith("/approve"):
        parts = stripped.split()
        if len(parts) != 3:
            print("  usage: /approve <request_id> <approved_by>")
            return
        res = await approve_request(int(parts[1]), parts[2])
        print(f"  {'Applied' if res.get('success') else 'Failed'}: "
              f"{res.get('message', res.get('status', ''))}")
        return
    if stripped.startswith("/reject"):
        parts = stripped.split()
        if len(parts) < 3:
            print("  usage: /reject <request_id> <rejected_by> [reason]")
            return
        reason = " ".join(parts[3:]) if len(parts) > 3 else ""
        res = await reject_request(int(parts[1]), parts[2], reason)
        print(f"  {'Rejected' if res.get('success') else 'Failed'}: "
              f"{res.get('message', res.get('status', ''))}")
        return

    # 3) Natural-language request -> intent router.
    #    First, rewrite context-dependent follow-ups ("apply the recommended
    #    action", "what about his bills?") into a self-contained request so the
    #    thread of conversation is preserved across turns.
    routed_text = _maybe_followup(stripped) or stripped
    payload = await router_run(routed_text)

    if RAW_MODE:
        print(json.dumps(payload, indent=2, default=str))
        return

    if not payload.get("success", True):
        print(f"  Sorry - {payload.get('message', 'something went wrong')}.")
        return

    kind, leaf = _find_write(payload)

    # Multi-step write (e.g. onboarding): stage all steps and ask to approve them
    # together. "Onboard" means the user wants this created, so we drive it to
    # completion on a single 'yes' instead of leaving 5 requests pending forever.
    steps = _onboarding_steps(leaf)
    if steps:
        cust = leaf.get("customer_number")
        acct = leaf.get("account_number")
        who = f" for {cust}" if cust else ""
        print(f"  I've prepared a {len(steps)}-step onboarding{who}"
              + (f" (account {acct})" if acct else "") + ":")
        for i, s in enumerate(steps, 1):
            print(f"    {i}. {s['description']} (request #{s['request_id']})")
        print("  Reply 'yes' to approve and apply ALL steps, or 'no' to cancel.")
        PENDING_BATCH = {"label": f"onboarding{who}", "steps": steps}
        _remember(stripped, f"Prepared {len(steps)}-step onboarding{who}.")
        return

    if kind == "no_change":
        msg = leaf.get('message', 'No change needed.')
        print(f"  {msg}")
        _remember(stripped, msg)
        return

    if kind == "pending":
        print("  " + _confirmation_text(leaf))
        desc = leaf.get("summary") or leaf.get("action") or "change"
        PENDING_APPROVAL = (leaf["request_id"], _APPROVER, desc, leaf)
        _remember(stripped, _confirmation_text(leaf))
        return

    # Read / everything else -> natural-language answer.
    # Capture RCA context first so a later "apply the recommendation" works.
    _capture_rca_context(leaf)
    answer = await _say(routed_text, leaf)
    print(answer)
    # If this was an RCA, list the recommended actions with numbers so the user
    # can pick one ("apply recommendation 2") and we keep the customer in scope.
    actions = leaf.get("recommended_actions") if isinstance(leaf, dict) else None
    if isinstance(actions, list) and actions:
        print("\n  Recommended actions (reply e.g. 'apply recommendation 1' or "
              "'apply all'):")
        for i, act in enumerate(actions, 1):
            print(f"    {i}. {act}")
    _remember(stripped, answer)


async def main() -> None:
    from src.db.pool import close_pool

    print("=" * 70)
    print("  TCL Finance & Billing - Chat Assistant")
    print("  Ask anything in plain English. /help for examples, /quit to exit.")
    print("=" * 70)

    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                line = await loop.run_in_executor(None, input, "\nyou > ")
            except (EOFError, KeyboardInterrupt):
                break
            try:
                await _handle(line)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001 — never crash the REPL
                print(f"  [error] {exc}")
    finally:
        await close_pool()
        print("\nGoodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
