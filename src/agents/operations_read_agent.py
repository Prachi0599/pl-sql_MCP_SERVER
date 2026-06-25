"""operations_read_agent — Natural language operations & data quality queries via GPT-4o function calling.

Exposes a single public coroutine:
    run(question: str) -> dict

9 tools: get_load_status_today, get_missing_loads, get_load_history,
         get_failed_load_summary, get_open_requests, get_requests_by_customer,
         get_inactive_entities, get_accounts_pending_termination,
         get_accounts_no_events
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import account as _account
from src.tools import power as _power
from src.tools import usage as _usage
from src.utils.audit import log_audit

_AGENT = "operations_read_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "You are an operations monitoring assistant for the TCL Finance & Billing Oracle database "
    "(schema: MCP_APP). Answer every question by calling one or more of the available tools. "
    "Never answer without calling a tool. "
    "For daily load status use get_load_status_today. "
    "For systems that haven't loaded recently use get_missing_loads. "
    "For service/support tickets use get_open_requests or get_requests_by_customer. "
    "For data quality issues combine get_failed_load_summary with get_accounts_no_events. "
    "For accounts near termination use get_accounts_pending_termination."
)

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_load_status_today",
            "description": (
                "Return today's load status for all source systems: "
                "records received, loaded, failed, and overall status. "
                "Use for 'did all systems send data today' questions."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_missing_loads",
            "description": (
                "Return source systems that have not loaded data within the last N days. "
                "Use for 'systems not loaded in X days' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days to look back (default 7)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_load_history",
            "description": "Return load history for a specific source system over the last N days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_system": {
                        "type": "string",
                        "description": "Source system name, e.g. MEDIATION",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back (default 30)",
                    },
                },
                "required": ["source_system"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_failed_load_summary",
            "description": (
                "Return a summary of failed loads by source system: "
                "failed load count, total records failed, error samples. "
                "Use for data quality and load failure investigations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back to summarise (default 7)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_requests",
            "description": (
                "Return open or in-progress service requests. "
                "Optionally filter by assigned_to (username). "
                "Use for 'open tickets assigned to X' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assigned_to": {
                        "type": "string",
                        "description": "Username to filter by, e.g. john.doe",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_requests_by_customer",
            "description": "Return all service requests (open and closed) for a specific customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"}
                },
                "required": ["customer_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inactive_entities",
            "description": "Return inactive customers and/or accounts. Filter by entity_type: CUSTOMER, ACCOUNT, or ALL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["CUSTOMER", "ACCOUNT", "ALL"],
                        "description": "CUSTOMER, ACCOUNT, or ALL (default ALL)",
                    },
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_accounts_pending_termination",
            "description": (
                "Return active accounts whose TERMINATION_DATE falls within the next N days. "
                "Use for 'accounts pending termination this week' (days_ahead=7)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Days ahead to look for terminations (default 30)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_accounts_no_events",
            "description": (
                "Return active accounts that have received no costed events this calendar month. "
                "Use for data quality checks: 'which accounts have no usage today/this month'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max rows (default 50)",
                    }
                },
                "required": [],
            },
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict) -> Any:
    if name == "get_load_status_today":
        return await _usage.get_load_status_today()
    if name == "get_missing_loads":
        return await _usage.get_missing_loads(args.get("days_back", 7))
    if name == "get_load_history":
        return await _usage.get_load_history(
            source_system=args["source_system"],
            days_back=args.get("days_back", 30),
        )
    if name == "get_failed_load_summary":
        return await _usage.get_failed_load_summary(args.get("days_back", 7))
    if name == "get_open_requests":
        return await _usage.get_open_requests(args.get("assigned_to"))
    if name == "get_requests_by_customer":
        return await _usage.get_requests_by_customer(args["customer_number"])
    if name == "get_inactive_entities":
        return await _power.get_inactive_entities(
            entity_type=args.get("entity_type"),
            limit=args.get("limit", 50),
        )
    if name == "get_accounts_pending_termination":
        return await _account.get_accounts_pending_termination(
            args.get("days_ahead", 30)
        )
    if name == "get_accounts_no_events":
        return await _power.get_accounts_no_events(args.get("limit", 50))
    return {"error": f"Unknown tool: {name}"}


# ── Public agent entry point ──────────────────────────────────────────────────

async def run(question: str) -> dict:
    """
    Answer a natural language operations question using GPT-4o function calling.

    Returns:
        {
          "success": True,
          "question": str,
          "tools_called": [{"tool": str, "args": dict}, ...],
          "results": [{"tool": str, "result": dict}, ...],
          "row_count": int,
        }
    """
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            tools=_TOOL_DEFS,
            tool_choice="required",
        )
    except Exception as exc:
        await log_audit(_AGENT, "", question[:100], "READ",
                        {"question": question}, "ERROR", str(exc))
        return {
            "success": False,
            "error_code": "OPENAI_ERROR",
            "message": str(exc),
        }

    msg = response.choices[0].message

    if not msg.tool_calls:
        await log_audit(_AGENT, "", question[:100], "READ",
                        {"question": question}, "ERROR", "No tool selected")
        return {
            "success": False,
            "error_code": "NO_TOOL_CALLED",
            "message": "Agent did not select an operations tool",
        }

    tools_called: list[dict] = []
    results: list[dict] = []

    for tc in msg.tool_calls:
        fn_name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        tools_called.append({"tool": fn_name, "args": args})
        tool_result = await _dispatch(fn_name, args)
        results.append({"tool": fn_name, "result": tool_result})

    await log_audit(
        _AGENT, "", question[:100], "READ",
        {"question": question, "tools_called": [t["tool"] for t in tools_called]},
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "tools_called": tools_called,
        "results": results,
        "row_count": len(results),
    }
