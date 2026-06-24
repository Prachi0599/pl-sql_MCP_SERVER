"""billing_read_agent — Natural language billing data queries via GPT-4o function calling.

Exposes a single public coroutine:
    run(question: str) -> dict

8 tools: get_bills_by_account, get_bill_by_invoice_number,
         get_billing_summary_by_customer, get_unpaid_bills,
         get_monthly_revenue, get_revenue_by_product_type,
         get_pending_adjustments, get_accounts_by_customer
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import account as _account
from src.tools import billing as _billing
from src.utils.audit import log_audit

_AGENT = "billing_read_agent"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are a billing data assistant for the TCL Finance & Billing Oracle database "
    "(schema: MCP_APP). Answer every question by calling one or more of the available tools. "
    "Never answer without calling a tool. "
    "For invoice lookups use get_bill_by_invoice_number. "
    "For account bill history use get_bills_by_account. "
    "For unpaid/outstanding totals use get_unpaid_bills. "
    "For revenue trends use get_monthly_revenue or get_revenue_by_product_type."
)

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_bills_by_account",
            "description": (
                "Return all bills for an account number. Optional filters: "
                "date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), "
                "status (UNPAID, PAID, CANCELLED)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "date_from":      {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to":        {"type": "string", "description": "YYYY-MM-DD"},
                    "status":         {"type": "string", "description": "UNPAID / PAID / CANCELLED"},
                },
                "required": ["account_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bill_by_invoice_number",
            "description": (
                "Return a single bill record by invoice number. "
                "Includes account, customer, amount, status, and creator details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {
                        "type": "string",
                        "description": "Invoice number, e.g. INV-8821",
                    }
                },
                "required": ["invoice_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_billing_summary_by_customer",
            "description": (
                "Return aggregate billing summary for a customer: "
                "total billed, outstanding amount, paid amount, invoice count."
            ),
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
            "name": "get_unpaid_bills",
            "description": (
                "Return all unpaid/outstanding bills across all customers. "
                "Optional currency filter. Use SUM of total_amount for overall outstanding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "currency_code": {
                        "type": "string",
                        "description": "Currency code filter, e.g. USD, EUR",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows (default 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_revenue",
            "description": (
                "Return monthly revenue totals (sum of TOTAL_AMOUNT, invoice count) "
                "for the last N months. For a specific month, request more months and filter client-side."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {
                        "type": "integer",
                        "description": "Number of past months to include (default 12)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_revenue_by_product_type",
            "description": "Return revenue broken down by product type (e.g. VOICE, DATA, MPLS).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_adjustments",
            "description": "Return all billing adjustments in PENDING status awaiting approval.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_accounts_by_customer",
            "description": (
                "Return all accounts for a customer number. Useful to discover "
                "account numbers before querying bills."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "status": {
                        "type": "string",
                        "description": "ACTIVE, INACTIVE, or omit for all",
                    },
                },
                "required": ["customer_number"],
            },
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict) -> Any:
    if name == "get_bills_by_account":
        return await _billing.get_bills_by_account(
            account_number=args["account_number"],
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            status=args.get("status"),
        )
    if name == "get_bill_by_invoice_number":
        return await _billing.get_bill_by_invoice_number(args["invoice_number"])
    if name == "get_billing_summary_by_customer":
        return await _billing.get_billing_summary_by_customer(args["customer_number"])
    if name == "get_unpaid_bills":
        return await _billing.get_unpaid_bills(
            currency_code=args.get("currency_code"),
            limit=args.get("limit", 50),
        )
    if name == "get_monthly_revenue":
        return await _billing.get_monthly_revenue(args.get("months", 12))
    if name == "get_revenue_by_product_type":
        return await _billing.get_revenue_by_product_type()
    if name == "get_pending_adjustments":
        return await _billing.get_pending_adjustments()
    if name == "get_accounts_by_customer":
        return await _account.get_accounts_by_customer(
            customer_number=args["customer_number"],
            status=args.get("status"),
        )
    return {"error": f"Unknown tool: {name}"}


# ── Public agent entry point ──────────────────────────────────────────────────

async def run(question: str) -> dict:
    """
    Answer a natural language billing question using GPT-4o function calling.

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
            "message": "Agent did not select a billing tool",
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
