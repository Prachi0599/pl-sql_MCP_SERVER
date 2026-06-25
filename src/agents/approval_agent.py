"""approval_agent — Natural language approval workflow via GPT-4o function-calling.

Pattern A: GPT-4o selects which of 4 approval tools to call.

Exposes a single public coroutine:
    run(question: str) -> dict

Tools: get_pending_approvals, get_my_pending_requests,
       approve_request, reject_request
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.tools import approval as _approval
from src.utils.audit import log_audit

_AGENT = "approval_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "You are an approval workflow agent for the TCL Finance & Billing system. "
    "Handle approval and rejection of pending write requests. "
    "Use get_pending_approvals to list all pending requests, "
    "get_my_pending_requests to list requests by a specific user, "
    "approve_request to approve a specific request ID, "
    "reject_request to reject a specific request ID with a reason. "
    "Always call exactly one tool. Never answer without calling a tool."
)

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_pending_approvals",
            "description": "List all PENDING approval requests, optionally filtered by requestor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requested_by": {"type": "string",
                                    "description": "Filter by requestor username"},
                    "limit": {"type": "integer",
                              "description": "Max rows to return (default 50)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_pending_requests",
            "description": "List PENDING requests submitted by a specific user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requested_by": {"type": "string",
                                    "description": "Username of the requestor"},
                    "limit": {"type": "integer"},
                },
                "required": ["requested_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_request",
            "description": "Approve a pending write request by its request_id. This executes the DML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id":  {"type": "integer",
                                   "description": "Approval request ID"},
                    "approved_by": {"type": "string",
                                   "description": "Username of the approver"},
                },
                "required": ["request_id", "approved_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_request",
            "description": "Reject a pending write request with a reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id":   {"type": "integer"},
                    "rejected_by":  {"type": "string"},
                    "reason":       {"type": "string",
                                    "description": "Reason for rejection"},
                },
                "required": ["request_id", "rejected_by"],
            },
        },
    },
]

async def _dispatch(name: str, args: dict) -> dict:
    fn = getattr(_approval, name)
    return await fn(**args)


async def run(question: str) -> dict:
    """
    Handle a natural language approval workflow request.

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
                        {"question": question[:100]}, "ERROR", "No tool selected")
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "Agent did not select an approval tool"}

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

    action_type = (
        "WRITE" if tools_called and
        tools_called[0]["tool"] in ("approve_request", "reject_request")
        else "READ"
    )

    await log_audit(
        _AGENT, "", question[:100], action_type,
        {"question": question[:100],
         "tools_called": [t["tool"] for t in tools_called]},
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "tools_called": tools_called,
        "results": results,
        "row_count": len(results),
    }
