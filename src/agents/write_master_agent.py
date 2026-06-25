"""write_master_agent — Routes natural language write requests to the correct sub-agent.

Pattern A: GPT-4o function-calling selects which of the 5 write sub-agents to invoke.

Exposes a single public coroutine:
    run(question: str) -> dict

Sub-agents (tools):
    onboarding_agent, billing_run_agent, dml_agent,
    approval_agent, adjustment_agent

Special dispatch:
    onboarding_agent  → run(params: dict)  — args dict passed directly as params
    billing_run_agent → run(billing_month, requested_by)
    others            → run(question: str)
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.agents import (
    adjustment_agent,
    approval_agent,
    billing_run_agent,
    dba_agent,
    dml_agent,
    onboarding_agent,
)
from src.utils.audit import log_audit

_AGENT = "write_master_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "You are the WRITE router for the TCL Finance & Billing system. Choose EXACTLY "
    "ONE write sub-agent. Every write is staged for approval — nothing changes "
    "immediately.\n\n"
    "- onboarding_agent: set up a BRAND-NEW customer end-to-end in one request "
    "(customer + address + contact + account + product together). Use only when the "
    "request clearly provides these details to create a new customer.\n"
    "- billing_run_agent: the MONTHLY BILLING RUN for all eligible accounts "
    "(e.g. 'run billing for 2026-06'); needs a billing month.\n"
    "- adjustment_agent: a billing ADJUSTMENT on an existing invoice — CREDIT, "
    "DISPUTE, or WAIVER.\n"
    "- approval_agent: manage the APPROVAL QUEUE — list pending approvals, or approve/"
    "reject a request by id.\n"
    "- dml_agent: ANY OTHER single write — create, update, or DELETE one customer, "
    "account, contact, address, bill, currency, provider, product assignment, costed "
    "event, service request, note, or a single status/flag change.\n"
    "- dba_agent: DATABASE-ADMINISTRATION maintenance — drop or rebuild an index "
    "('remove unwanted indexing'), gather/refresh table statistics, or recompile an "
    "invalid object.\n\n"
    "Disambiguation:\n"
    "- One field/status change, one new single record, or deleting one note/address/"
    "contact/event -> dml_agent.\n"
    "- Full new-customer setup with multiple linked records -> onboarding_agent.\n"
    "- Credit / refund / waiver / dispute on an invoice -> adjustment_agent.\n"
    "- Approve, reject, or list pending requests -> approval_agent.\n"
    "- Index/statistics/recompile maintenance -> dba_agent.\n"
    "Always call exactly one tool. Never answer without calling a tool."
)

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "onboarding_agent",
            "description": (
                "Onboard a new customer end-to-end: creates customer record, "
                "address, contact, account, and assigns a product — all in 5 steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name":      {"type": "string"},
                    "company_code":       {"type": "string"},
                    "customer_type_code": {"type": "string"},
                    "address_type":       {"type": "string"},
                    "address_line1":      {"type": "string"},
                    "city":               {"type": "string"},
                    "country":            {"type": "string"},
                    "contact_name":       {"type": "string"},
                    "designation":        {"type": "string"},
                    "email":              {"type": "string"},
                    "phone_number":       {"type": "string"},
                    "account_name":       {"type": "string"},
                    "currency_code":      {"type": "string"},
                    "product_code":       {"type": "string"},
                    "start_date":         {"type": "string", "description": "YYYY-MM-DD"},
                    "requested_by":       {"type": "string"},
                },
                "required": [
                    "customer_name", "company_code", "customer_type_code",
                    "address_type", "address_line1", "city", "country",
                    "contact_name", "designation", "email",
                    "account_name", "currency_code", "product_code",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "billing_run_agent",
            "description": "Execute the monthly billing run for all MONTHLY-cycle accounts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "billing_month": {
                        "type": "string",
                        "description": "Target billing month, e.g. 2026-06",
                    },
                    "requested_by": {"type": "string"},
                },
                "required": ["billing_month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dml_agent",
            "description": (
                "Handle any single write operation: create or update customers, "
                "accounts, contacts, addresses, bills, events, service requests, "
                "products, providers, currencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's write request"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approval_agent",
            "description": (
                "Handle approval workflow: list pending approvals, "
                "approve or reject a specific request by ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's approval request"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjustment_agent",
            "description": (
                "Create a billing adjustment (CREDIT, DISPUTE, or WAIVER) for an invoice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's adjustment request"},
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
                "Database-administration maintenance: drop or rebuild an index, "
                "gather/refresh table statistics, or recompile an invalid object."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's DBA maintenance request"},
                },
                "required": ["question"],
            },
        },
    },
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "onboarding_agent":
        return await onboarding_agent.run(args)
    if name == "billing_run_agent":
        return await billing_run_agent.run(
            args["billing_month"],
            args.get("requested_by", "mcp_user"),
        )
    if name == "dml_agent":
        return await dml_agent.run(args.get("question", ""))
    if name == "approval_agent":
        return await approval_agent.run(args.get("question", ""))
    if name == "adjustment_agent":
        return await adjustment_agent.run(args.get("question", ""))
    if name == "dba_agent":
        return await dba_agent.run(args.get("question", ""))
    return {"success": False, "error_code": "UNKNOWN_AGENT",
            "message": f"Unknown write agent: {name}"}


async def run(question: str) -> dict:
    """
    Route a write request to the appropriate write sub-agent.

    Returns:
        {
          "success": True,
          "question": str,
          "routed_to": str,
          "result": dict,
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
        await log_audit(_AGENT, "", question[:100], "WRITE",
                        {"question": question[:100]}, "ERROR", str(exc))
        return {"success": False, "error_code": "OPENAI_ERROR", "message": str(exc)}

    msg = response.choices[0].message

    if not msg.tool_calls:
        await log_audit(_AGENT, "", question[:100], "WRITE",
                        {"question": question[:100]}, "ERROR", "No sub-agent selected")
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "Router did not select a write sub-agent"}

    tc = msg.tool_calls[0]
    routed_to = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    sub_result = await _dispatch(routed_to, args)

    await log_audit(
        _AGENT, "", question[:100], "WRITE",
        {"question": question[:100], "routed_to": routed_to},
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "routed_to": routed_to,
        "result": sub_result,
    }
