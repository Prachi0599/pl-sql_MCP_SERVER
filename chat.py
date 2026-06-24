"""
Interactive chat client for the TCL Finance & Billing MCP Server.

This is a REPL that lets you talk to the server in plain English. Every line you
type is sent to the intent_router agent — the same top-level entry point a real
MCP client (e.g. Claude Desktop) would reach — which classifies it as READ or
WRITE, routes it to the right master agent and sub-agent, and returns a result.

Run from the project root:

    python chat.py

Requires a populated .env (DB_USER, DB_PASSWORD, DB_CONNECT_STRING, OPENAI_API_KEY).

Slash commands:
    /help                 show examples and commands
    /raw                  toggle full raw-JSON output on/off
    /read   <question>    force routing through read_master_agent
    /write  <question>    force routing through write_master_agent
    /pending              list all PENDING approval requests
    /approve <id> <user>  approve a pending request (executes the staged DML)
    /reject  <id> <user>  reject a pending request
    /quit  |  /exit       leave the chat
"""
from __future__ import annotations

import asyncio
import json
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

EXAMPLES = """
Try asking (plain English — no SQL needed):

  READ examples
    * How many active customers do we have?
    * Show me the monthly revenue for the last 6 months
    * List all PL/SQL packages in the schema
    * What are the top 5 accounts by usage this month?
    * Investigate billing and usage issues for customer CUST000122
    * Give me an executive revenue summary

  WRITE examples (these stage an approval request - nothing changes until approved)
    * Create a new currency GBP called British Pound, requested by alice
    * Apply a $250 CREDIT adjustment to invoice INV00000123 for account ACC000123
    * Run the monthly billing for 2026-06

  Then approve a staged request:
    /pending
    /approve 42 alice
"""


def _print_result(payload: dict) -> None:
    """Pretty-print an intent_router / agent result."""
    if RAW_MODE:
        print(json.dumps(payload, indent=2, default=str))
        return

    if not payload.get("success", False):
        print(f"  [x] {payload.get('error_code', 'ERROR')}: "
              f"{payload.get('message', 'unknown error')}")
        return

    # Top-level router envelope: intent + routed_to
    intent = payload.get("intent")
    routed = payload.get("routed_to")
    path = []
    if intent:
        path.append(intent)
    if routed:
        path.append(routed)

    inner = payload.get("result", payload)
    # Drill one more level (master agent → sub-agent)
    sub_routed = inner.get("routed_to") if isinstance(inner, dict) else None
    if sub_routed:
        path.append(sub_routed)
    final = inner.get("result", inner) if isinstance(inner, dict) else inner

    if path:
        print(f"  route: {' -> '.join(str(p) for p in path)}")

    # Show the most useful field for each common shape
    if isinstance(final, dict):
        if "rca_summary" in final:
            print(f"  RCA summary: {final['rca_summary']}")
            if final.get("recommended_actions"):
                for a in final["recommended_actions"]:
                    print(f"    - {a}")
        if "narrative" in final:
            print(f"  {final['narrative']}")
        if "request_id" in final:
            print(f"  approval request #{final['request_id']} -> "
                  f"status {final.get('status', '?')}")
        if "approval_ids" in final:
            print(f"  queued {len(final['approval_ids'])} bills "
                  f"(billing_month {final.get('billing_month')})")
        if "steps" in final:
            print(f"  onboarding: {final.get('steps_completed')}/"
                  f"{final.get('total_steps')} steps staged")

    # Always show the payload (compact unless it is large)
    blob = json.dumps(final, indent=2, default=str)
    if len(blob) > 2000:
        blob = blob[:2000] + "\n  ... (truncated - use /raw for full output)"
    print(blob)


async def _handle(line: str) -> None:
    from src.agents.intent_router import run as router_run
    from src.agents.read_master_agent import run as read_run
    from src.agents.write_master_agent import run as write_run
    from src.tools.approval import (
        get_pending_approvals, approve_request, reject_request,
    )

    global RAW_MODE
    stripped = line.strip()
    if not stripped:
        return

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
        _print_result(await get_pending_approvals())
        return
    if stripped.startswith("/approve"):
        parts = stripped.split()
        if len(parts) != 3:
            print("  usage: /approve <request_id> <approved_by>")
            return
        _print_result(await approve_request(int(parts[1]), parts[2]))
        return
    if stripped.startswith("/reject"):
        parts = stripped.split()
        if len(parts) < 3:
            print("  usage: /reject <request_id> <rejected_by> [reason]")
            return
        reason = " ".join(parts[3:]) if len(parts) > 3 else ""
        _print_result(await reject_request(int(parts[1]), parts[2], reason))
        return
    if stripped.startswith("/read "):
        _print_result(await read_run(stripped[6:]))
        return
    if stripped.startswith("/write "):
        _print_result(await write_run(stripped[7:]))
        return

    # Default: full natural-language routing
    _print_result(await router_run(stripped))


async def main() -> None:
    from src.db.pool import close_pool

    print("=" * 70)
    print("  TCL Finance & Billing — MCP Chat Client")
    print("  Type a question in plain English. /help for examples, /quit to exit.")
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
                print(f"  [x] unexpected error: {exc}")
    finally:
        await close_pool()
        print("\nGoodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
