"""adjustment_agent — Billing adjustment requests via GPT-4o function-calling.

Pattern A: GPT-4o selects create_billing_adjustment with args.

Exposes a single public coroutine:
    run(question: str) -> dict

Agent-level guard: adjustment_amount must be > 0 (checked after GPT-4o extracts args,
before any DB call). Invalid amounts return VALIDATION_ERROR immediately.
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.tools import writes as _writes
from src.utils.audit import log_audit

_AGENT = "adjustment_agent"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are a billing adjustment agent for the TCL Finance & Billing system. "
    "Extract the adjustment details from the user's request and call "
    "create_billing_adjustment with the correct parameters. "
    "adjustment_type must be one of: CREDIT, DISPUTE, WAIVER. "
    "adjustment_amount must be a positive number. "
    "Always call the tool — never answer without calling it."
)

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_billing_adjustment",
            "description": (
                "Create a billing adjustment (credit, dispute, or waiver) "
                "for an invoice. Returns a PENDING approval request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {
                        "type": "string",
                        "description": "Invoice number to adjust (e.g. INV-001234)",
                    },
                    "account_number": {
                        "type": "string",
                        "description": "Account number associated with the invoice",
                    },
                    "adjustment_type": {
                        "type": "string",
                        "enum": ["CREDIT", "DISPUTE", "WAIVER"],
                        "description": "Type of adjustment",
                    },
                    "adjustment_amount": {
                        "type": "number",
                        "description": "Positive amount of the adjustment",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the adjustment",
                    },
                    "requested_by": {
                        "type": "string",
                        "description": "Username requesting the adjustment",
                    },
                },
                "required": [
                    "invoice_number", "account_number", "adjustment_type",
                    "adjustment_amount", "reason",
                ],
            },
        },
    },
]


async def run(question: str) -> dict:
    """
    Create a billing adjustment from a natural language request.

    Agent-level guard rejects adjustment_amount <= 0 before any DB call.

    Returns:
        {
          "success": bool,
          "question": str,
          "action": "create_billing_adjustment",
          "request_id": int | None,
          "status": "PENDING",
          "summary": str,
          "details": dict,
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
                        {"question": question[:100]}, "ERROR", "No tool selected")
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "Agent did not select an adjustment tool"}

    tc = msg.tool_calls[0]
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    # ── Agent-level guard: amount must be positive ────────────────────────────
    amount = args.get("adjustment_amount")
    if amount is None or float(amount) <= 0:
        await log_audit(_AGENT, "", question[:100], "WRITE",
                        {"question": question[:100],
                         "adjustment_amount": amount},
                        "ERROR", "adjustment_amount must be positive")
        return {
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "message": "adjustment_amount must be a positive number",
        }

    tool_result = await _writes.create_billing_adjustment(**args)

    await log_audit(
        _AGENT, "", question[:100], "WRITE",
        {"question": question[:100],
         "adjustment_type": args.get("adjustment_type"),
         "adjustment_amount": amount,
         "request_id": tool_result.get("request_id")},
        "SUCCESS" if tool_result.get("success") else "ERROR",
    )

    return {
        "success": tool_result.get("success", False),
        "question": question,
        "action": "create_billing_adjustment",
        "request_id": tool_result.get("request_id"),
        "status": tool_result.get("status", "PENDING"),
        "summary": tool_result.get("summary", ""),
        "details": tool_result,
    }
