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
# When a write is staged, holds (request_id, approver, human_description) until
# the user confirms or cancels it.
PENDING_APPROVAL: tuple | None = None
_APPROVER = "chat_user"

_AFFIRMATIVE = {"yes", "y", "approve", "approved", "confirm", "ok", "okay",
                "go ahead", "proceed", "do it", "sure"}
_NEGATIVE = {"no", "n", "cancel", "reject", "stop", "abort", "nevermind"}

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
    "Never mention JSON, tools, agents, routing, or internal field names. "
    "If the data is empty or null, say that no matching records were found."
)


async def _say(question: str, data: dict) -> str:
    """Turn a structured result into a natural-language answer via GPT-4o."""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    blob = json.dumps(data, default=str)
    if len(blob) > 6000:
        blob = blob[:6000] + " ...(truncated)"
    try:
        resp = await _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PRESENTER_SYSTEM},
                {"role": "user",
                 "content": f"Question: {question}\n\nData returned:\n{blob}"},
            ],
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


# ── command + message handling ────────────────────────────────────────────────

async def _resolve_pending(affirm: bool) -> None:
    """Approve or reject the change currently awaiting confirmation."""
    global PENDING_APPROVAL
    from src.tools.approval import approve_request, reject_request
    request_id, approver, desc = PENDING_APPROVAL
    PENDING_APPROVAL = None
    if affirm:
        res = await approve_request(request_id, approver)
        if res.get("success"):
            extra = ""
            dml = res.get("dml_result") or {}
            pq = dml.get("post_query_result") or {}
            if pq:
                extra = f" ({', '.join(f'{k}={v}' for k, v in pq.items())})"
            print(f"  Done - approved and applied (request #{request_id}).{extra}")
        else:
            print(f"  Could not apply it: {res.get('message', res.get('error_code'))}")
    else:
        await reject_request(request_id, approver, "cancelled by user in chat")
        print(f"  Cancelled - no changes were made (request #{request_id} rejected).")


async def _handle(line: str) -> None:
    global RAW_MODE, PENDING_APPROVAL
    from src.agents.intent_router import run as router_run
    from src.tools.approval import (
        get_pending_approvals, approve_request, reject_request,
    )

    stripped = line.strip()
    if not stripped:
        return

    low = stripped.lower()

    # 1) If a change is awaiting confirmation, interpret yes/no first.
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

    # 3) Natural-language request -> intent router
    payload = await router_run(stripped)

    if RAW_MODE:
        print(json.dumps(payload, indent=2, default=str))
        return

    if not payload.get("success", True):
        print(f"  Sorry - {payload.get('message', 'something went wrong')}.")
        return

    kind, leaf = _find_write(payload)

    if kind == "no_change":
        print(f"  {leaf.get('message', 'No change needed.')}")
        return

    if kind == "pending":
        print("  " + _confirmation_text(leaf))
        desc = leaf.get("summary") or leaf.get("action") or "change"
        PENDING_APPROVAL = (leaf["request_id"], _APPROVER, desc)
        return

    # Read / everything else -> natural-language answer
    print(await _say(stripped, leaf))


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
