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
    insight_agent,
    operations_read_agent,
    rca_agent,
    schema_agent,
    usage_read_agent,
)
from src.utils.audit import log_audit

_AGENT = "read_master_agent"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are a master read router for the TCL Finance & Billing system. "
    "Given a user question, select exactly ONE sub-agent to handle it:\n"
    "- schema_agent: questions about database schema, packages, procedures, tables, columns\n"
    "- customer_read_agent: customer info, contacts, addresses, products, account lookups\n"
    "- billing_read_agent: bills, invoices, adjustments, payment status, revenue by account\n"
    "- usage_read_agent: usage events, bandwidth trends, anomalies, source systems, failed events\n"
    "- operations_read_agent: pipeline load status, service requests, inactive entities, operational health\n"
    "- rca_agent: root-cause analysis for a specific customer (requires a customer number)\n"
    "- insight_agent: executive revenue summaries, product performance trends, financial insights\n"
    "Always call exactly one tool. Never answer without calling a tool."
)

_AGENT_MAP = {
    "schema_agent":           schema_agent,
    "customer_read_agent":    customer_read_agent,
    "billing_read_agent":     billing_read_agent,
    "usage_read_agent":       usage_read_agent,
    "operations_read_agent":  operations_read_agent,
    "insight_agent":          insight_agent,
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
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "rca_agent":
        return await rca_agent.run(args["customer_number"])
    sub = _AGENT_MAP[name]
    return await sub.run(args.get("question", ""))


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
