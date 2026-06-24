"""intent_router — Top-level READ vs WRITE classifier and dispatcher.

Pattern A: GPT-4o function-calling selects route_to_read_master or route_to_write_master.

Exposes a single public coroutine:
    run(question: str) -> dict

READ signals: query, show, list, find, investigate, analyze, what, how many, who, which
WRITE signals: create, add, update, onboard, bill, adjust, approve, reject, assign, terminate

Dispatches to:
    read_master_agent.run(question)   → intent "READ"
    write_master_agent.run(question)  → intent "WRITE"
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.agents import read_master_agent, write_master_agent
from src.utils.audit import log_audit

_AGENT = "intent_router"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are the INTENT classifier for the TCL Finance & Billing system. Decide "
    "whether the user wants to READ information or WRITE/modify data, then route.\n\n"
    "route_to_read_master — the user wants to retrieve, view, count, analyze, "
    "investigate, or understand existing data or the schema. "
    "Signals: show, list, get, find, what, which, who, how many, how much, report, "
    "summary, analyze, investigate, diagnose, explain, compare, trend.\n\n"
    "route_to_write_master — the user wants to create, change, remove, process, or "
    "approve data. "
    "Signals: create, add, new, register, update, change, set, modify, delete, "
    "remove, terminate, onboard, run billing, generate bill, adjust, credit, waive, "
    "dispute, assign, resolve, ingest, approve, reject.\n\n"
    "Rules:\n"
    "- A request that only ASKS ABOUT data is READ, even if it names an entity that "
    "could be changed ('how many active customers' is READ).\n"
    "- A request that asks to CHANGE state is WRITE, even if phrased as a question "
    "('can you set account X to inactive' is WRITE).\n"
    "- When genuinely ambiguous, prefer route_to_read_master.\n"
    "Always call exactly one tool. Never answer without calling a tool."
)

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "route_to_read_master",
            "description": (
                "Route to the read master agent for queries, lookups, reports, "
                "analysis, and schema discovery."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's question or request",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_write_master",
            "description": (
                "Route to the write master agent for create, update, onboard, "
                "billing run, adjustment, approval, and all other write operations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's write request",
                    },
                },
                "required": ["question"],
            },
        },
    },
]

_INTENT_MAP = {
    "route_to_read_master":  ("READ",  "read_master_agent"),
    "route_to_write_master": ("WRITE", "write_master_agent"),
}


async def run(question: str) -> dict:
    """
    Classify and route a user question to the appropriate master agent.

    Returns:
        {
          "success": True,
          "question": str,
          "intent": "READ" | "WRITE",
          "routed_to": "read_master_agent" | "write_master_agent",
          "result": dict,             # full master agent response
        }
    """
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            tools=_TOOL_DEFS,
            tool_choice="required",
        )
    except Exception as exc:
        await log_audit(_AGENT, "", question[:100], "READ",
                        {"question": question[:100]}, "ERROR", str(exc))
        return {"success": False, "error_code": "OPENAI_ERROR", "message": str(exc)}

    msg = response.choices[0].message

    if not msg.tool_calls:
        await log_audit(_AGENT, "", question[:100], "READ",
                        {"question": question[:100]}, "ERROR", "No route selected")
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "Router did not select a route"}

    tc = msg.tool_calls[0]
    tool_name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    routed_question = args.get("question", question)
    intent, routed_to = _INTENT_MAP.get(tool_name, ("READ", "read_master_agent"))

    if routed_to == "read_master_agent":
        master_result = await read_master_agent.run(routed_question)
    else:
        master_result = await write_master_agent.run(routed_question)

    action_type = intent  # "READ" or "WRITE"
    await log_audit(
        _AGENT, "", question[:100], action_type,
        {"question": question[:100], "intent": intent, "routed_to": routed_to},
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "intent": intent,
        "routed_to": routed_to,
        "result": master_result,
    }
