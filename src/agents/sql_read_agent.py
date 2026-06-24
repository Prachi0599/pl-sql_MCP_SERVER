"""sql_read_agent — Universal read access via safe, GPT-4o-generated SQL.

This is the catch-all data agent: it can answer essentially any *read* question
about MCP_APP by generating a single read-only SELECT, validating it, executing
it with a hard row cap, and returning the rows. It exists so the assistant can
answer arbitrary questions (specific field lookups, lists, counts, ad-hoc
filters) that the curated per-domain agents don't have a dedicated tool for.

Exposes a single public coroutine:
    run(question: str) -> dict

Safety:
  * Only a single SELECT/WITH statement is allowed.
  * Any DML/DDL/PLSQL keyword (insert/update/delete/merge/drop/alter/create/
    truncate/grant/revoke/exec/begin/declare/call/commit/rollback) is rejected.
  * No semicolons (no statement chaining).
  * The generated query is wrapped in an outer ROWNUM cap as a hard backstop.
"""
from __future__ import annotations

import os
import re

from openai import AsyncOpenAI

from src.db.pool import get_connection
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_AGENT = "sql_read_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
_MAX_ROWS = 200

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"exec|execute|begin|declare|call|commit|rollback|into)\b",
    re.IGNORECASE,
)

# Cached compact schema description (built once per process).
_schema_cache: str | None = None

_SYSTEM_PROMPT = (
    "You are an expert Oracle SQL generator for the TCL Finance & Billing database "
    "(schema MCP_APP). Given the schema and a user question, produce EXACTLY ONE "
    "read-only Oracle SQL SELECT statement that answers it.\n\n"
    "Hard rules:\n"
    "- Output ONLY the SQL — no prose, no markdown, no semicolon.\n"
    "- SELECT (or WITH ... SELECT) only. Never INSERT/UPDATE/DELETE/DDL/PLSQL.\n"
    "- Always schema-qualify tables as MCP_APP.<TABLE>.\n"
    "- Match codes case-insensitively with UPPER(col)=UPPER('value').\n"
    "- Cap rows: add `FETCH FIRST 50 ROWS ONLY` unless the user asks for a specific N "
    "or an aggregate.\n"
    "- For 'top N' use ORDER BY <metric> DESC FETCH FIRST N ROWS ONLY.\n\n"
    "Business keys & joins:\n"
    "- CUSTOMER.CUSTOMER_NUMBER (e.g. CUST000122) is the customer business id; "
    "CUSTOMER_ID is the internal PK.\n"
    "- ACCOUNT.ACCOUNT_NUMBER (e.g. ACC000123); ACCOUNT.CUSTOMER_ID -> CUSTOMER.CUSTOMER_ID; "
    "ACCOUNT.CURRENCY_ID -> CURRENCY.CURRENCY_ID.\n"
    "- BILL_SUMMARY.ACCOUNT_ID -> ACCOUNT.ACCOUNT_ID; BILL_SUMMARY.INVOICE_NUMBER "
    "(e.g. INV00000123), BILL_STATUS.\n"
    "- ACCOUNT_DETAILS.ACCOUNT_ID -> ACCOUNT (BILLABLE_FLAG, COMMISSIONING_DATE, "
    "TERMINATION_DATE).\n"
    "- COSTED_EVENT.ACCOUNT_ID -> ACCOUNT (usage events).\n"
    "- CUSTOMER.INV_COMPANY_ID -> INVOICING_COMPANY; CUSTOMER.CUSTOMER_TYPE_ID -> CUSTOMER_TYPE.\n"
    "When the user says 'customer 3' they usually mean CUSTOMER_NUMBER or CUSTOMER_ID = 3 "
    "— prefer matching CUSTOMER_NUMBER, falling back to CUSTOMER_ID."
)


async def _exec(conn, sql: str, params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


async def _load_schema(conn) -> str:
    """Build a rich schema description: columns, foreign keys, and the real
    distinct values of low-cardinality 'enum' columns. Cached per process so the
    generated SQL is accurate (correct joins and correct status/code values)."""
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    # 1. Columns per table
    cols_rows = await _exec(conn, """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM   ALL_TAB_COLUMNS
        WHERE  OWNER = 'MCP_APP'
        ORDER BY TABLE_NAME, COLUMN_ID
    """)
    tables: dict[str, list[str]] = {}
    for r in cols_rows:
        tables.setdefault(r["table_name"], []).append(r["column_name"])
    tables_block = "\n".join(
        f"{t}({', '.join(cols)})" for t, cols in sorted(tables.items())
    )

    # 2. Foreign keys (child.col -> parent)
    fk_rows = await _exec(conn, """
        SELECT ac.TABLE_NAME, acc.COLUMN_NAME, ac2.TABLE_NAME AS ref_table
        FROM   ALL_CONSTRAINTS ac
        JOIN   ALL_CONS_COLUMNS acc
               ON acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME AND acc.OWNER = ac.OWNER
        JOIN   ALL_CONSTRAINTS ac2
               ON ac2.CONSTRAINT_NAME = ac.R_CONSTRAINT_NAME AND ac2.OWNER = ac.OWNER
        WHERE  ac.OWNER = 'MCP_APP' AND ac.CONSTRAINT_TYPE = 'R'
        ORDER BY ac.TABLE_NAME, acc.COLUMN_NAME
    """)
    fk_block = "\n".join(
        f"{f['table_name']}.{f['column_name']} -> {f['ref_table']}" for f in fk_rows
    )

    # 3. Distinct values of low-cardinality enum-like columns
    cand = await _exec(conn, """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM   ALL_TAB_COLUMNS
        WHERE  OWNER = 'MCP_APP'
          AND  DATA_TYPE LIKE '%CHAR%'
          AND (COLUMN_NAME LIKE '%STATUS%' OR COLUMN_NAME LIKE '%TYPE%'
               OR COLUMN_NAME LIKE '%FLAG%' OR COLUMN_NAME IN
               ('BILLING_CYCLE','SOURCE_SYSTEM','COUNTRY','CURRENCY_CODE','PRODUCT_TYPE'))
        ORDER BY TABLE_NAME, COLUMN_NAME
    """)
    enum_lines: list[str] = []
    for c in cand:
        t, col = c["table_name"], c["column_name"]
        try:
            vals = await _exec(
                conn,
                f"SELECT DISTINCT {col} AS v FROM MCP_APP.{t} "
                f"WHERE {col} IS NOT NULL FETCH FIRST 26 ROWS ONLY")
            values = [str(v["v"]) for v in vals]
            if 0 < len(values) <= 25:
                enum_lines.append(f"{t}.{col}: {', '.join(values)}")
        except Exception:
            continue
    enum_block = "\n".join(enum_lines)

    _schema_cache = (
        f"TABLES (name(columns)):\n{tables_block}\n\n"
        f"FOREIGN KEYS (child.column -> parent table):\n{fk_block}\n\n"
        f"COMMON COLUMN VALUES (use these exact values):\n{enum_block}"
    )
    return _schema_cache


def _clean_sql(raw: str) -> str:
    sql = (raw or "").strip()
    if sql.startswith("```"):
        sql = sql.split("```")[1]
        if sql.lower().startswith("sql"):
            sql = sql[3:]
    return sql.strip().rstrip(";").strip()


def _is_safe(sql: str) -> tuple[bool, str]:
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "Only SELECT queries are allowed."
    if ";" in sql:
        return False, "Multiple statements are not allowed."
    # Allow CREATE-free: the regex would catch 'create'; but 'created_dtm' is a column.
    # Use word boundaries and ignore matches that are part of an identifier.
    for m in _FORBIDDEN.finditer(sql):
        token = m.group(0).lower()
        start, end = m.span()
        # skip if part of a larger identifier (e.g. CREATED_DTM contains 'create')
        prev_ch = sql[start - 1] if start > 0 else " "
        next_ch = sql[end] if end < len(sql) else " "
        if prev_ch == "_" or next_ch == "_" or prev_ch.isalnum() or next_ch.isalnum():
            continue
        return False, f"Disallowed keyword '{token}' in query."
    return True, ""


async def run(question: str) -> dict:
    """Answer an arbitrary read question by generating and running safe SQL.

    Returns {success, question, sql, data:[...], row_count} or an error dict.
    """
    conn = await get_connection()
    try:
        schema = await _load_schema(conn)

        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        try:
            resp = await client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",
                     "content": f"Schema:\n{schema}\n\nQuestion: {question}\n\nSQL:"},
                ],
                temperature=0,
            )
        except Exception as exc:
            await log_audit(_AGENT, "", question[:100], "READ",
                            {"question": question[:100]}, "ERROR", str(exc))
            return {"success": False, "error_code": "OPENAI_ERROR", "message": str(exc)}

        sql = _clean_sql(resp.choices[0].message.content or "")
        safe, reason = _is_safe(sql)
        if not safe:
            await log_audit(_AGENT, "", question[:100], "READ",
                            {"question": question[:100], "sql": sql[:300]},
                            "ERROR", reason)
            return {"success": False, "error_code": "UNSAFE_QUERY", "message": reason,
                    "sql": sql}

        capped = f"SELECT * FROM (\n{sql}\n) WHERE ROWNUM <= {_MAX_ROWS}"
        try:
            data = await _exec(conn, capped)
        except Exception as exc:
            await log_audit(_AGENT, "", question[:100], "READ",
                            {"question": question[:100], "sql": sql[:300]},
                            "ERROR", str(exc))
            err = map_oracle_error(exc)
            err["sql"] = sql
            return err

        await log_audit(_AGENT, "", question[:100], "READ",
                        {"question": question[:100], "sql": sql[:300],
                         "row_count": len(data)}, "SUCCESS")
        return {"success": True, "question": question, "sql": sql,
                "data": data, "row_count": len(data)}
    finally:
        await conn.close()
