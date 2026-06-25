"""read_master_agent — Routes natural language read questions to the correct sub-agent.

Pattern A: GPT-4o function-calling selects which of the 7 read sub-agents to invoke.

Exposes a single public coroutine:
    run(question: str) -> dict

Sub-agents (tools):
    schema_agent, customer_read_agent, billing_read_agent,
    usage_read_agent, operations_read_agent, rca_agent, insight_agent
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.agents import (
    billing_read_agent,
    customer_read_agent,
    dba_agent,
    insight_agent,
    operations_read_agent,
    rca_agent,
    schema_agent,
    sql_read_agent,
    usage_read_agent,
)
from src.utils.audit import log_audit

_AGENT = "read_master_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "You are the READ router for the TCL Finance & Billing system. Choose EXACTLY "
    "ONE sub-agent that best answers the question, matching on its PRIMARY subject:\n\n"
    "- customer_read_agent: anything about CUSTOMERS as entities — look up a customer, "
    "their contacts, addresses, subscribed products, account list, customer health, AND "
    "customer counts / totals / summary statistics (e.g. 'how many active customers', "
    "'customers by type').\n"
    "- billing_read_agent: BILLS and INVOICES — a specific invoice, bills for an account, "
    "unpaid/overdue bills, a customer's billing summary, billing adjustments, revenue for "
    "a single account.\n"
    "- usage_read_agent: USAGE and network EVENTS — costed events, bandwidth/data usage, "
    "top usage accounts, usage anomalies, failed events, events by source system.\n"
    "- operations_read_agent: OPERATIONAL health of the data platform — daily load/pipeline "
    "status, missing or failed loads, service-request tickets, INACTIVE entities, accounts "
    "with no events. NOT for customer counts.\n"
    "- rca_agent: deep root-cause INVESTIGATION for ONE named customer (needs a customer "
    "number) — 'investigate / diagnose / why is X wrong for customer ...'.\n"
    "- schema_agent: DATABASE STRUCTURE — tables, columns, packages, procedures, sequences, "
    "indexes — 'what tables/packages exist', 'describe table', 'parameters of procedure X'.\n"
    "- insight_agent: EXECUTIVE financial narratives across the whole business — total "
    "revenue trends, revenue by product type, period/quarterly summaries, top-line KPIs.\n"
    "- dba_agent: DATABASE ADMINISTRATION / performance & health — 'is the database slow', "
    "database health, deadlocks / blocking / lock contention, slow queries / query "
    "optimization, wait events, tablespace / space usage, INVALID objects, unused or "
    "redundant indexes ('remove unwanted indexing'), stale optimizer statistics, "
    "long-running operations.\n"
    "- sql_read_agent: GENERAL-PURPOSE data lookups — any specific record, field, list, "
    "id, count, or ad-hoc filter that the agents above don't squarely cover. Examples: "
    "'show account details for ACC000123', 'list all account numbers', 'top 5 customer "
    "ids', 'what currency does customer CUST000122 use', 'which accounts are INACTIVE'. "
    "When unsure which read agent fits, use sql_read_agent — it can answer anything from "
    "the data.\n\n"
    "Disambiguation:\n"
    "- Company-wide revenue / executive summary -> insight_agent; one account's bills -> billing_read_agent.\n"
    "- 'How many customers ...' -> customer_read_agent (it owns customer statistics).\n"
    "- Investigating a specific customer's problem -> rca_agent; a plain customer lookup -> customer_read_agent.\n"
    "- A specific account/bill/record field lookup, an arbitrary list/filter, or anything "
    "not clearly owned above -> sql_read_agent.\n"
    "Always call exactly one tool. Never answer without calling a tool."
)

_AGENT_MAP = {
    "schema_agent":           schema_agent,
    "customer_read_agent":    customer_read_agent,
    "billing_read_agent":     billing_read_agent,
    "usage_read_agent":       usage_read_agent,
    "operations_read_agent":  operations_read_agent,
    "insight_agent":          insight_agent,
    "dba_agent":              dba_agent,
    "sql_read_agent":         sql_read_agent,
}

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "schema_agent",
            "description": (
                "Route to the schema agent. Handles questions about database structure: "
                "packages, procedures, tables, columns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_read_agent",
            "description": (
                "Route to the customer read agent. Handles customer lookups, contacts, "
                "addresses, products, account searches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "billing_read_agent",
            "description": (
                "Route to the billing read agent. Handles bill lookups, invoice status, "
                "adjustments, unpaid bills, revenue by account."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "usage_read_agent",
            "description": (
                "Route to the usage read agent. Handles usage events, bandwidth trends, "
                "anomalies, failed events, source system queries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "operations_read_agent",
            "description": (
                "Route to the operations read agent. Handles pipeline load status, "
                "service request groups, inactive entities, accounts with no events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rca_agent",
            "description": (
                "Route to the root-cause analysis agent for a specific customer. "
                "Use when the user wants to diagnose billing or data issues for a named customer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {
                        "type": "string",
                        "description": "Customer number to analyze, e.g. CUST-001",
                    },
                },
                "required": ["customer_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insight_agent",
            "description": (
                "Route to the insight agent for executive-level financial reports: "
                "revenue trends, product performance, outstanding payments, period summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dba_agent",
            "description": (
                "Database-administration & performance agent. Use for database "
                "health, slow queries / query optimization, deadlocks / blocking, "
                "wait events, tablespace & space usage, invalid objects, unused or "
                "redundant indexes, stale statistics, and long-running operations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_read_agent",
            "description": (
                "General-purpose data query agent. Use for any specific record, field, "
                "list, id, count, or ad-hoc filter not squarely owned by the other read "
                "agents (e.g. account details by number, all account numbers, top-N ids, "
                "a customer's currency). The safe fallback that can answer anything from "
                "the data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question"},
                },
                "required": ["question"],
            },
        },
    },
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "rca_agent":
        return await rca_agent.run(args["customer_number"])
    sub = _AGENT_MAP[name]
    return await sub.run(args.get("question", ""))


# Data-retrieval agents whose empty/failed result should fall back to SQL.
_DATA_AGENTS = {
    "customer_read_agent", "billing_read_agent",
    "usage_read_agent", "operations_read_agent",
}


def _failed(res: dict) -> bool:
    """True only if a sub-agent could not answer (errored / selected no tool).

    We deliberately do NOT treat a successful-but-empty result as a failure: a
    specialized agent reporting 'none found' is a valid answer, and falling back
    to SQL there could replace a correct empty answer with a misleading one. The
    fallback exists to rescue hard failures (OPENAI_ERROR, NO_TOOL_CALLED, etc.)."""
    return not (isinstance(res, dict) and res.get("success", False))


async def run(question: str) -> dict:
    """
    Route a read question to the appropriate sub-agent via GPT-4o function-calling.

    Returns:
        {
          "success": True,
          "question": str,
          "routed_to": str,
          "result": dict,          # the sub-agent's full response
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
                        {"question": question[:100]}, "ERROR", "No sub-agent selected")
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "Router did not select a sub-agent"}

    # Use only the first tool call (routing should be singular)
    tc = msg.tool_calls[0]
    routed_to = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    sub_result = await _dispatch(routed_to, args)

    # Safety net: if a specialized data agent could not answer (hard failure),
    # retry via the universal SQL agent. Only replace when SQL actually succeeds.
    if routed_to in _DATA_AGENTS and _failed(sub_result):
        fallback = await sql_read_agent.run(question)
        if fallback.get("success"):
            routed_to = "sql_read_agent"
            sub_result = fallback

    await log_audit(
        _AGENT, "", question[:100], "READ",
        {"question": question[:100], "routed_to": routed_to},
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "routed_to": routed_to,
        "result": sub_result,
    }
