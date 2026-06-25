"""usage_read_agent — Natural language usage analytics queries via GPT-4o function calling.

Exposes a single public coroutine:
    run(question: str) -> dict

7 tools: get_events_by_account, get_event_summary, get_top_usage_accounts,
         get_events_by_source_system, get_bandwidth_trend,
         get_failed_events, get_usage_anomalies
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import usage as _usage
from src.utils.audit import log_audit

_AGENT = "usage_read_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "You are a usage analytics assistant for the TCL Finance & Billing Oracle database "
    "(schema: MCP_APP). Answer every question by calling one or more of the available tools. "
    "Never answer without calling a tool. "
    "For per-account usage use get_events_by_account or get_event_summary. "
    "For top consumers use get_top_usage_accounts. "
    "For anomalies or accounts exceeding a threshold use get_usage_anomalies. "
    "For bandwidth trends over time use get_bandwidth_trend. "
    "For failed or errored events use get_failed_events or get_events_by_source_system."
)

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_events_by_account",
            "description": (
                "Return costed events for a specific account number. "
                "Supports optional date_from / date_to filters (YYYY-MM-DD). "
                "Use for 'usage for ACC-X this month' style questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "date_from":      {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to":        {"type": "string", "description": "YYYY-MM-DD"},
                    "limit":          {"type": "integer", "description": "Max rows (default 50)"},
                },
                "required": ["account_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_summary",
            "description": (
                "Return aggregate usage summary for an account: "
                "event count, total bits, avg/max speed, date range. "
                "Optional date_from / date_to filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "date_from":      {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to":        {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["account_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_usage_accounts",
            "description": "Return the top N accounts ranked by total bandwidth consumption.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of top accounts to return (default 10)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_events_by_source_system",
            "description": (
                "Return costed events filtered by source system name (e.g. MEDIATION, RATING). "
                "Optional status filter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_system": {
                        "type": "string",
                        "description": "Source system name, e.g. MEDIATION",
                    },
                    "status": {
                        "type": "string",
                        "description": "Event status filter, e.g. FAILED, SUCCESS",
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["source_system"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bandwidth_trend",
            "description": (
                "Return bandwidth usage trend aggregated by DAY or MONTH. "
                "Optionally scoped to a specific account. "
                "Use granularity='DAY' for daily breakdown, 'MONTH' for monthly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {
                        "type": "string",
                        "description": "Account number to scope results (optional)",
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["DAY", "MONTH"],
                        "description": "DAY or MONTH (default DAY)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of periods to return (default 30)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_failed_events",
            "description": (
                "Return events with a non-SUCCESS status. "
                "Optionally filter by source_system. "
                "Use for 'failed events from MEDIATION' style questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_system": {
                        "type": "string",
                        "description": "Filter by source system, e.g. MEDIATION",
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
            "name": "get_usage_anomalies",
            "description": (
                "Return accounts or events where SPEED_MBPS exceeds a given threshold. "
                "Use for 'accounts exceeding X Mbps' style questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold_mbps": {
                        "type": "number",
                        "description": "Speed threshold in Mbps (default 100)",
                    }
                },
                "required": [],
            },
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict) -> Any:
    if name == "get_events_by_account":
        return await _usage.get_events_by_account(
            account_number=args["account_number"],
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            limit=args.get("limit", 50),
        )
    if name == "get_event_summary":
        return await _usage.get_event_summary(
            account_number=args["account_number"],
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
    if name == "get_top_usage_accounts":
        return await _usage.get_top_usage_accounts(args.get("limit", 10))
    if name == "get_events_by_source_system":
        return await _usage.get_events_by_source_system(
            source_system=args["source_system"],
            status=args.get("status"),
            limit=args.get("limit", 50),
        )
    if name == "get_bandwidth_trend":
        return await _usage.get_bandwidth_trend(
            account_number=args.get("account_number"),
            granularity=args.get("granularity", "DAY"),
            limit=args.get("limit", 30),
        )
    if name == "get_failed_events":
        return await _usage.get_failed_events(
            source_system=args.get("source_system"),
            limit=args.get("limit", 50),
        )
    if name == "get_usage_anomalies":
        return await _usage.get_usage_anomalies(
            threshold_mbps=args.get("threshold_mbps", 100.0)
        )
    return {"error": f"Unknown tool: {name}"}


# ── Public agent entry point ──────────────────────────────────────────────────

async def run(question: str) -> dict:
    """
    Answer a natural language usage analytics question using GPT-4o function calling.

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
            "message": "Agent did not select a usage tool",
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
