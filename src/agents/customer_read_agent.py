"""customer_read_agent — Natural language customer data queries via GPT-4o function calling.

Exposes a single public coroutine:
    run(question: str) -> dict

11 tools: search_customers, get_customer_360, get_customer_addresses,
          get_customer_contacts, get_customer_products, get_customer_health_check,
          get_customer_summary_stats, get_expiring_products,
          get_customer_by_number, get_customers_by_company, search_contacts_by_email
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import account as _account
from src.tools import billing as _billing
from src.tools import customer as _customer
from src.tools import power as _power
from src.utils.audit import log_audit

_AGENT = "customer_read_agent"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are a customer data assistant for the TCL Finance & Billing Oracle database "
    "(schema: MCP_APP). Answer every question by calling one or more of the available tools. "
    "Never answer without calling a tool. "
    "For contact queries use get_customer_contacts. "
    "For full customer details use get_customer_360. "
    "For company/region filters use get_customers_by_company."
)

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_customers",
            "description": "Search customers by name fragment and/or status (ACTIVE/INACTIVE).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name":   {"type": "string", "description": "Partial customer name"},
                    "status": {"type": "string", "description": "ACTIVE or INACTIVE"},
                    "limit":  {"type": "integer", "description": "Max rows (default 50)"},
                    "offset": {"type": "integer", "description": "Pagination offset"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_360",
            "description": (
                "Return a full 360 view for a customer: profile, addresses, contacts, "
                "accounts, products, and latest bill."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {
                        "type": "string",
                        "description": "Customer number, e.g. CUST-100",
                    }
                },
                "required": ["customer_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_by_number",
            "description": "Look up a single customer record by its unique customer number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {
                        "type": "string",
                        "description": "Customer number, e.g. CUST-100",
                    }
                },
                "required": ["customer_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customers_by_company",
            "description": "List customers belonging to a specific invoicing company/region code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_code": {
                        "type": "string",
                        "description": "Invoicing company code, e.g. EMEA-01",
                    },
                    "status": {
                        "type": "string",
                        "description": "ACTIVE, INACTIVE, or ALL (default ACTIVE)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows (default 50)",
                    },
                },
                "required": ["company_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_addresses",
            "description": "Return all addresses (billing, shipping, etc.) for a customer.",
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
            "name": "get_customer_contacts",
            "description": (
                "Return all contacts (name, email, phone, designation) for a customer. "
                "Use this when someone asks 'who is the contact for CUST-X'."
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
            "name": "search_contacts_by_email",
            "description": "Find contacts whose email matches a given pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_pattern": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["email_pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_products",
            "description": "Return products subscribed by a customer, optionally filtered by status.",
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
    {
        "type": "function",
        "function": {
            "name": "get_customer_health_check",
            "description": (
                "Run a health check for a customer: flags for missing address, "
                "no active products, unpaid bills, and no usage events this month."
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
            "name": "get_customer_summary_stats",
            "description": "Return aggregate stats: total, active, inactive customer counts broken down by type.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expiring_products",
            "description": (
                "Return active customer products whose END_DATE falls within the next N days. "
                "Use days_ahead=30 for 'this month', 7 for 'this week'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Number of days ahead to look (default 30)",
                    }
                },
                "required": [],
            },
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict) -> Any:
    if name == "search_customers":
        return await _customer.search_customers(
            name=args.get("name"),
            status=args.get("status"),
            limit=args.get("limit", 50),
            offset=args.get("offset", 0),
        )
    if name == "get_customer_360":
        return await _customer.get_customer_360(args["customer_number"])
    if name == "get_customer_by_number":
        return await _customer.get_customer_by_number(args["customer_number"])
    if name == "get_customers_by_company":
        return await _customer.get_customers_by_company(
            company_code=args["company_code"],
            status=args.get("status", "ACTIVE"),
            limit=args.get("limit", 50),
        )
    if name == "get_customer_addresses":
        return await _account.get_customer_addresses(args["customer_number"])
    if name == "get_customer_contacts":
        return await _account.get_customer_contacts(args["customer_number"])
    if name == "search_contacts_by_email":
        return await _account.search_contacts_by_email(
            email_pattern=args["email_pattern"],
            limit=args.get("limit", 50),
        )
    if name == "get_customer_products":
        return await _billing.get_customer_products(
            customer_number=args["customer_number"],
            status=args.get("status"),
        )
    if name == "get_customer_health_check":
        return await _power.get_customer_health_check(args["customer_number"])
    if name == "get_customer_summary_stats":
        return await _customer.get_customer_summary_stats()
    if name == "get_expiring_products":
        return await _power.get_expiring_products(args.get("days_ahead", 30))
    return {"error": f"Unknown tool: {name}"}


# ── Public agent entry point ──────────────────────────────────────────────────

async def run(question: str) -> dict:
    """
    Answer a natural language customer question using GPT-4o function calling.

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
            "message": "Agent did not select a customer tool",
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
