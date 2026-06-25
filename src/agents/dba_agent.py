"""dba_agent — Natural-language DBA / database-administration agent.

Pattern A: the model selects exactly one DBA tool via function-calling.

Handles BOTH:
  * Read diagnostics  — database health, slow queries, deadlocks/blocking,
    wait events, tablespace usage, invalid objects, unused/redundant indexes,
    stale stats, long-running operations. These return data immediately.
  * Maintenance writes — drop/rebuild an index, gather table stats, recompile
    an object. These are staged as PENDING approval requests (no DDL/DML runs
    until approve_request is called), exactly like every other write.

Exposes a single public coroutine:
    run(question: str) -> dict
"""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from src.tools import dba as _dba
from src.utils.audit import log_audit

_AGENT = "dba_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# Maintenance actions that stage an approval request rather than reading data.
_WRITE_TOOLS = {"drop_index", "rebuild_index", "gather_table_stats",
                "recompile_object"}

_SYSTEM_PROMPT = (
    "You are a senior Oracle DBA assistant for the TCL Finance & Billing "
    "database (schema MCP_APP). Translate the user's request into exactly one "
    "DBA tool call.\n"
    "- For diagnostics / 'is the DB slow', health, locks, deadlocks, blocking, "
    "slow queries, wait events, space/tablespace, invalid objects, unused or "
    "redundant indexes, stale statistics, long operations: call the matching "
    "read tool.\n"
    "- For maintenance ACTIONS (drop an index, rebuild an index, gather/refresh "
    "statistics for a table, recompile an invalid object): call the matching "
    "write tool. These are staged for human approval before they run.\n"
    "Never invent object names — use exactly what the user gave. Always call a tool."
)

_TOOL_DEFS: list[dict] = [
    {"type": "function", "function": {
        "name": "get_database_health",
        "description": "Overall database/schema health snapshot: version, invalid "
                       "objects, size, stale-stats count, long operations.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_active_sessions",
        "description": "List current user sessions connected to the database.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_blocking_sessions",
        "description": "Find blocking locks / lock contention / deadlock risk.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_slow_queries",
        "description": "Top SQL by average elapsed time — query-optimization "
                       "candidates.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_wait_events",
        "description": "Top database wait events by time waited.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_tablespace_usage",
        "description": "Space usage per tablespace.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_segment_sizes",
        "description": "Largest segments (tables/indexes) in the schema.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_invalid_objects",
        "description": "List INVALID objects that need recompilation.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_unused_indexes",
        "description": "Secondary (non-constraint) indexes to review for removal "
                       "/ 'remove unwanted indexing'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_redundant_indexes",
        "description": "Indexes whose columns are a prefix of another index "
                       "(redundant).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_table_stats_status",
        "description": "Tables with missing or stale optimizer statistics.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_long_operations",
        "description": "Long-running operations currently in progress (slowdown).",
        "parameters": {"type": "object", "properties": {}}}},
    # ── maintenance writes ──────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "drop_index",
        "description": "Drop a non-constraint index (staged for approval).",
        "parameters": {"type": "object", "properties": {
            "index_name": {"type": "string"},
            "requested_by": {"type": "string"}}, "required": ["index_name"]}}},
    {"type": "function", "function": {
        "name": "rebuild_index",
        "description": "Rebuild/defragment an index (staged for approval).",
        "parameters": {"type": "object", "properties": {
            "index_name": {"type": "string"},
            "requested_by": {"type": "string"}}, "required": ["index_name"]}}},
    {"type": "function", "function": {
        "name": "gather_table_stats",
        "description": "Gather/refresh optimizer statistics for a table "
                       "(staged for approval).",
        "parameters": {"type": "object", "properties": {
            "table_name": {"type": "string"},
            "requested_by": {"type": "string"}}, "required": ["table_name"]}}},
    {"type": "function", "function": {
        "name": "recompile_object",
        "description": "Recompile an INVALID package/procedure/view "
                       "(staged for approval).",
        "parameters": {"type": "object", "properties": {
            "object_name": {"type": "string"},
            "requested_by": {"type": "string"}}, "required": ["object_name"]}}},
]


async def _dispatch(name: str, args: dict) -> dict:
    fn = getattr(_dba, name, None)
    if fn is None or not callable(fn):
        return {"success": False, "error_code": "UNKNOWN_TOOL",
                "message": f"Unknown DBA tool: {name}"}
    try:
        return await fn(**args)
    except TypeError as exc:
        return {"success": False, "error_code": "INVALID_ARGS",
                "message": (f"Could not run '{name}' - missing or invalid "
                            f"details ({exc}).")}


async def run(question: str) -> dict:
    """Route a natural-language DBA request to exactly one DBA tool.

    Returns:
        {success, question, action, kind: 'READ'|'WRITE', result|details, ...}
    """
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
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
        return {"success": False, "error_code": "NO_TOOL_CALLED",
                "message": "DBA agent did not select a tool"}

    tc = msg.tool_calls[0]
    action = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    tool_result = await _dispatch(action, args)
    kind = "WRITE" if action in _WRITE_TOOLS else "READ"

    await log_audit(_AGENT, "", question[:100], kind,
                    {"question": question[:100], "action": action},
                    "SUCCESS" if tool_result.get("success") else "ERROR")

    result = {
        "success": tool_result.get("success", False),
        "question": question,
        "action": action,
        "kind": kind,
        "result": tool_result,
    }
    if kind == "WRITE":
        # Surface approval fields so the chat client can run its confirm flow.
        result["details"] = tool_result
        for key in ("request_id", "status", "summary", "no_change", "message"):
            if key in tool_result:
                result[key] = tool_result[key]
    return result
