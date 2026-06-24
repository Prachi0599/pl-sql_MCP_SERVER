"""schema_agent — Natural language schema exploration via OpenAI function calling.

Exposes a single public coroutine:
    run(question: str) -> dict

The agent:
  1. Sends the user question + schema tool definitions to GPT-4o.
  2. Executes every tool call GPT-4o selects (may be multiple).
  3. Logs TOOL_NAME='schema_agent' in MCP_AUDIT_LOG.
  4. Returns {success, question, tools_called, results}.
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import schema as _schema
from src.utils.audit import log_audit

_AGENT = "schema_agent"
_MODEL = "gpt-4o"

_SYSTEM_PROMPT = (
    "You are a database schema assistant for the TCL Finance & Billing Oracle database "
    "(schema: MCP_APP). Answer every question by calling one or more of the available tools. "
    "Never answer without calling a tool.\n"
    "Tool selection guidance:\n"
    "- Parameters / arguments / signature of a specific procedure or function "
    "(e.g. 'what parameters does BILLING_PKG.GENERATE_BILL take') -> call "
    "get_procedure_signature with the package and procedure names.\n"
    "- Which procedures/functions a package contains -> list_package_procedures.\n"
    "- Which packages exist -> list_packages.\n"
    "- Columns/constraints of a table -> describe_table (for relationship questions, "
    "call describe_table for BOTH tables so FK constraints are visible)."
)

# ── OpenAI tool definitions ───────────────────────────────────────────────────

_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_packages",
            "description": "List all PL/SQL packages in MCP_APP schema with their names.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_package_procedures",
            "description": "List all procedures and functions inside a given PL/SQL package.",
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "The exact package name, e.g. BILLING_PKG",
                    }
                },
                "required": ["package_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_procedure_signature",
            "description": "Return the parameter list (name, type, direction) for a specific procedure or function.",
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {"type": "string"},
                    "procedure_name": {"type": "string"},
                },
                "required": ["package_name", "procedure_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "Return all columns and foreign-key constraints for a given table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table name in MCP_APP schema, e.g. CUSTOMER",
                    }
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_procedure_for_table",
            "description": "Find all PL/SQL package lines that reference a given table — useful to discover which procedures read or write a table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table name to search for, e.g. BILL_SUMMARY",
                    }
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List all tables in MCP_APP schema with approximate row counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sequences",
            "description": "List all Oracle sequences in MCP_APP schema.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_indexes",
            "description": "List indexes for a specific table, or all indexes if no table is given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Optional table name to filter indexes",
                    }
                },
                "required": [],
            },
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict) -> Any:
    """Call the matching schema tool and return its result."""
    if name == "list_packages":
        return await _schema.list_packages()
    if name == "list_package_procedures":
        return await _schema.list_package_procedures(args["package_name"])
    if name == "get_procedure_signature":
        return await _schema.get_procedure_signature(
            args["package_name"], args["procedure_name"]
        )
    if name == "describe_table":
        return await _schema.describe_table(args["table_name"])
    if name == "find_procedure_for_table":
        return await _schema.find_procedure_for_table(args["table_name"])
    if name == "list_tables":
        return await _schema.list_tables()
    if name == "list_sequences":
        return await _schema.list_sequences()
    if name == "list_indexes":
        return await _schema.list_indexes(args.get("table_name") or None)
    return {"error": f"Unknown tool: {name}"}


# ── Public agent entry point ──────────────────────────────────────────────────

async def run(question: str) -> dict:
    """
    Answer a natural language schema question using GPT-4o function calling.

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
            "message": "Agent did not select a schema tool",
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
