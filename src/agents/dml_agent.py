"""dml_agent — Natural language write operations via GPT-4o function-calling.

Pattern A: GPT-4o selects which write tool to call.

Exposes a single public coroutine:
    run(question: str) -> dict

Safety: mass-DML guard rejects questions matching
    r'\\b(delete|update|remove)\\s+all\\b' before any GPT-4o call.

All write tools return {success, request_id, status:'PENDING', ...} — no
actual DML is committed until approve_request() is called.
"""
from __future__ import annotations

import json
import os
import re

from openai import AsyncOpenAI

from src.tools import writes as _writes
from src.utils.audit import log_audit

_AGENT = "dml_agent"
_MODEL = "gpt-4o"

_MASS_DML = re.compile(r"\b(delete|update|remove)\s+all\b", re.IGNORECASE)

_SYSTEM_PROMPT = (
    "You are a write operations agent for the TCL Finance & Billing Oracle database. "
    "Translate the user's request into exactly one write tool call. "
    "All writes create a PENDING approval request — no DML is committed immediately. "
    "Always pass 'requested_by' from the question context, defaulting to 'mcp_user'. "
    "Never answer without calling a tool."
)

# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    # ── Group A: Provider ─────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_provider",
            "description": "Create a new telecom provider.",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_code":  {"type": "string"},
                    "provider_name":  {"type": "string"},
                    "service_type":   {"type": "string"},
                    "country":        {"type": "string"},
                    "requested_by":   {"type": "string"},
                },
                "required": ["provider_code", "provider_name", "service_type", "country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_provider_status",
            "description": "Update a provider's status (ACTIVE/INACTIVE).",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_code": {"type": "string"},
                    "new_status":    {"type": "string", "enum": ["ACTIVE", "INACTIVE"]},
                    "requested_by":  {"type": "string"},
                },
                "required": ["provider_code", "new_status"],
            },
        },
    },
    # ── Group B: Customer ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_customer",
            "description": "Create a new customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name":      {"type": "string"},
                    "company_code":       {"type": "string"},
                    "customer_type_code": {"type": "string"},
                    "requested_by":       {"type": "string"},
                },
                "required": ["customer_name", "company_code", "customer_type_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_customer_status",
            "description": "Update a customer's status (ACTIVE/INACTIVE/TERMINATED).",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "new_status":      {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "new_status"],
            },
        },
    },
    # ── Group C: Address & Contact ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "add_customer_address",
            "description": "Add a billing or shipping address for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "address_type":    {"type": "string"},
                    "address_line1":   {"type": "string"},
                    "city":            {"type": "string"},
                    "country":         {"type": "string"},
                    "state":           {"type": "string"},
                    "postal_code":     {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "address_type", "address_line1",
                             "city", "country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_customer_contact",
            "description": "Add a contact (name, email, phone) for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number":  {"type": "string"},
                    "contact_name":     {"type": "string"},
                    "designation":      {"type": "string"},
                    "email":            {"type": "string"},
                    "phone_number":     {"type": "string"},
                    "alternate_email":  {"type": "string"},
                    "requested_by":     {"type": "string"},
                },
                "required": ["customer_number", "contact_name", "designation", "email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_contact_email",
            "description": "Update a contact's email address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id":   {"type": "integer"},
                    "new_email":    {"type": "string"},
                    "requested_by": {"type": "string"},
                },
                "required": ["contact_id", "new_email"],
            },
        },
    },
    # ── Group D: Account ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_account",
            "description": "Create a new account for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "account_name":    {"type": "string"},
                    "currency_code":   {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "account_name", "currency_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_account_status",
            "description": "Update an account's status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "new_status":     {"type": "string"},
                    "requested_by":   {"type": "string"},
                },
                "required": ["account_number", "new_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_account_billable",
            "description": "Set account billable flag to Y or N.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "billable_flag":  {"type": "string", "enum": ["Y", "N"]},
                    "requested_by":   {"type": "string"},
                },
                "required": ["account_number", "billable_flag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_account_currency",
            "description": "Change an account's billing currency (e.g. set ACC000123 to INR).",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "currency_code":  {"type": "string", "description": "e.g. USD, INR, GBP"},
                    "requested_by":   {"type": "string"},
                },
                "required": ["account_number", "currency_code"],
            },
        },
    },
    # ── Group E: Products ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "assign_product_to_account",
            "description": "Assign a product to a customer account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "account_number":  {"type": "string"},
                    "product_code":    {"type": "string"},
                    "start_date":      {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date":        {"type": "string", "description": "YYYY-MM-DD"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "account_number", "product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_customer_product",
            "description": "Terminate an active product for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "product_code":    {"type": "string"},
                    "end_date":        {"type": "string", "description": "YYYY-MM-DD"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "product_code"],
            },
        },
    },
    # ── Group F: Billing ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_bill",
            "description": "Generate a bill for an account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string"},
                    "bill_amount":    {"type": "number"},
                    "tax_amount":     {"type": "number"},
                    "currency_code":  {"type": "string"},
                    "requested_by":   {"type": "string"},
                },
                "required": ["account_number", "bill_amount", "tax_amount",
                             "currency_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_bill_status",
            "description": "Update the status of a bill (PAID/UNPAID/DISPUTED).",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string"},
                    "new_status":     {"type": "string"},
                    "requested_by":   {"type": "string"},
                },
                "required": ["invoice_number", "new_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_billing_adjustment",
            "description": "Create a billing adjustment (CREDIT, DISPUTE, or WAIVER).",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number":     {"type": "string"},
                    "account_number":     {"type": "string"},
                    "adjustment_type":    {"type": "string",
                                          "enum": ["CREDIT", "DISPUTE", "WAIVER"]},
                    "adjustment_amount":  {"type": "number"},
                    "reason":             {"type": "string"},
                    "requested_by":       {"type": "string"},
                },
                "required": ["invoice_number", "account_number", "adjustment_type",
                             "adjustment_amount", "reason"],
            },
        },
    },
    # ── Group G: Costed Event ──────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "ingest_costed_event",
            "description": "Ingest a costed usage event for an account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_number":  {"type": "string"},
                    "event_dtm":       {"type": "string",
                                       "description": "YYYY-MM-DD HH24:MI:SS"},
                    "in_bits":         {"type": "integer"},
                    "out_bits":        {"type": "integer"},
                    "speed_mbps":      {"type": "number"},
                    "bandwidth_mbps":  {"type": "number"},
                    "event_type":      {"type": "string"},
                    "source_system":   {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["account_number", "event_dtm", "in_bits", "out_bits",
                             "speed_mbps", "bandwidth_mbps"],
            },
        },
    },
    # ── Group I: Service Requests & Notes ──────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_service_request",
            "description": "Create a service request for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "request_type":    {"type": "string"},
                    "priority":        {"type": "string",
                                       "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "description":     {"type": "string"},
                    "raised_by":       {"type": "string"},
                    "account_number":  {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "request_type", "priority",
                             "description", "raised_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_service_request",
            "description": "Assign a service request to a support agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id":   {"type": "integer"},
                    "assigned_to":  {"type": "string"},
                    "requested_by": {"type": "string"},
                },
                "required": ["request_id", "assigned_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_service_request",
            "description": "Mark a service request as resolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id":        {"type": "integer"},
                    "resolution_notes":  {"type": "string"},
                    "resolved_by":       {"type": "string"},
                    "requested_by":      {"type": "string"},
                },
                "required": ["request_id", "resolution_notes", "resolved_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_customer_note",
            "description": "Add an internal note for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_number": {"type": "string"},
                    "note_type":       {"type": "string"},
                    "note_text":       {"type": "string"},
                    "created_by":      {"type": "string"},
                    "requested_by":    {"type": "string"},
                },
                "required": ["customer_number", "note_type", "note_text", "created_by"],
            },
        },
    },
    # ── Group J: Currency ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_currency",
            "description": "Create a new currency record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency_code": {"type": "string"},
                    "currency_name": {"type": "string"},
                    "requested_by":  {"type": "string"},
                },
                "required": ["currency_code", "currency_name"],
            },
        },
    },
]

async def _dispatch(name: str, args: dict) -> dict:
    fn = getattr(_writes, name, None)
    if fn is None or not callable(fn):
        return {"success": False, "error_code": "UNKNOWN_TOOL",
                "message": f"Unknown write tool: {name}"}
    try:
        return await fn(**args)
    except TypeError as exc:
        # GPT-4o omitted a required argument (or passed an unexpected one).
        return {"success": False, "error_code": "INVALID_ARGS",
                "message": (f"Could not perform '{name}' - some required details "
                            f"were missing or invalid ({exc}).")}


async def run(question: str) -> dict:
    """
    Translate a natural language write request into a write tool call.

    Returns:
        {
          "success": True,
          "question": str,
          "action": str,        # tool called
          "request_id": int,    # approval request ID (PENDING)
          "status": "PENDING",
          "summary": str,
          "details": dict,      # full write tool response
        }

    Mass-DML guard:
        Questions matching r'\\b(delete|update|remove)\\s+all\\b' are rejected
        immediately without any DB or OpenAI call.
    """
    if _MASS_DML.search(question):
        return {
            "success": False,
            "error_code": "MASS_DML_REFUSED",
            "message": (
                "Mass DML operations are not permitted. "
                "Specify a single target (customer, account, invoice, etc.)."
            ),
        }

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
                "message": "Agent did not select a write tool"}

    tc = msg.tool_calls[0]
    action = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    tool_result = await _dispatch(action, args)

    await log_audit(
        _AGENT, "", question[:100], "WRITE",
        {"question": question[:100], "action": action,
         "request_id": tool_result.get("request_id")},
        "SUCCESS" if tool_result.get("success") else "ERROR",
    )

    result = {
        "success": tool_result.get("success", False),
        "question": question,
        "action": action,
        "request_id": tool_result.get("request_id"),
        "status": tool_result.get("status", "PENDING"),
        "summary": tool_result.get("summary", ""),
        "details": tool_result,
    }
    # Propagate no-op detection and before/after values so callers (and the chat
    # client) can show a meaningful "already set" or "change from X to Y" message.
    for key in ("no_change", "message", "current_value", "requested_value"):
        if key in tool_result:
            result[key] = tool_result[key]
    return result
