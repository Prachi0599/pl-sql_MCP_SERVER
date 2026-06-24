"""Group L — Schema Introspection Tools (8 tools).

All tools log to MCP_AUDIT_LOG via log_audit and return
{ success, data, row_count } or { success, error_code, message }.
"""
from __future__ import annotations

import json
from typing import Any

import oracledb

from src.db.pool import get_connection
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "schema"
_PKG = "METADATA_PKG"


async def _exec(sql: str, params: list | None = None) -> list[dict]:
    """Run a SELECT, return list of row dicts."""
    conn = await get_connection()
    try:
        with conn.cursor() as cur:
            await cur.execute(sql, params or [])
            cols = [d[0].lower() for d in cur.description]
            rows = await cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        await conn.close()


def _ok(data: Any, row_count: int | None = None) -> dict:
    result: dict = {"success": True, "data": data}
    if row_count is not None:
        result["row_count"] = row_count
    return result


# ── L1: list_tables ──────────────────────────────────────────────────────────

async def list_tables() -> dict:
    sql = """
        SELECT t.TABLE_NAME,
               NVL(c.NUM_ROWS, 0) AS row_count,
               t.COMMENTS
        FROM   (
            SELECT at2.TABLE_NAME,
                   tc.COMMENTS
            FROM   ALL_TABLES at2
            LEFT JOIN ALL_TAB_COMMENTS tc
                   ON tc.TABLE_NAME  = at2.TABLE_NAME
                  AND tc.OWNER       = at2.OWNER
            WHERE  at2.OWNER = 'MCP_APP'
        ) t
        LEFT JOIN ALL_TAB_STATISTICS c
               ON c.TABLE_NAME = t.TABLE_NAME
              AND c.OWNER      = 'MCP_APP'
        ORDER BY t.TABLE_NAME
    """
    try:
        rows = await _exec(sql)
        await log_audit(_TOOL, "", "list_tables", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "list_tables", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L2: describe_table ────────────────────────────────────────────────────────

async def describe_table(table_name: str) -> dict:
    table_upper = table_name.upper()
    col_sql = """
        SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE, DATA_DEFAULT
        FROM   ALL_TAB_COLUMNS
        WHERE  OWNER      = 'MCP_APP'
          AND  TABLE_NAME = :1
        ORDER BY COLUMN_ID
    """
    con_sql = """
        SELECT ac.CONSTRAINT_NAME, ac.CONSTRAINT_TYPE,
               acc.COLUMN_NAME,
               ac.R_CONSTRAINT_NAME,
               (
                   SELECT TABLE_NAME FROM ALL_CONSTRAINTS
                   WHERE  CONSTRAINT_NAME = ac.R_CONSTRAINT_NAME
                     AND  OWNER = 'MCP_APP'
               ) AS REF_TABLE
        FROM   ALL_CONSTRAINTS  ac
        JOIN   ALL_CONS_COLUMNS acc
               ON acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME
              AND acc.OWNER           = ac.OWNER
        WHERE  ac.OWNER       = 'MCP_APP'
          AND  ac.TABLE_NAME  = :1
          AND  ac.CONSTRAINT_TYPE IN ('P','U','R')
        ORDER BY ac.CONSTRAINT_TYPE, ac.CONSTRAINT_NAME
    """
    try:
        cols = await _exec(col_sql, [table_upper])
        if not cols:
            await log_audit(_TOOL, "", "describe_table", "READ",
                            {"table_name": table_name}, "SUCCESS")
            return _ok(None, 0)
        cons = await _exec(con_sql, [table_upper])
        data = {"table_name": table_upper, "columns": cols, "constraints": cons}
        await log_audit(_TOOL, "", "describe_table", "READ",
                        {"table_name": table_name}, "SUCCESS")
        return _ok(data, len(cols))
    except Exception as exc:
        await log_audit(_TOOL, "", "describe_table", "READ",
                        {"table_name": table_name}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L3: list_packages ─────────────────────────────────────────────────────────

async def list_packages() -> dict:
    sql = """
        SELECT OBJECT_NAME AS package_name, STATUS
        FROM   ALL_OBJECTS
        WHERE  OWNER       = 'MCP_APP'
          AND  OBJECT_TYPE = 'PACKAGE'
        ORDER BY OBJECT_NAME
    """
    try:
        rows = await _exec(sql)
        await log_audit(_TOOL, _PKG, "LIST_PACKAGES", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, _PKG, "LIST_PACKAGES", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L4: list_package_procedures ───────────────────────────────────────────────

async def list_package_procedures(package_name: str) -> dict:
    pkg_upper = package_name.upper()
    sql = """
        SELECT DISTINCT PROCEDURE_NAME AS procedure_name
        FROM   ALL_PROCEDURES
        WHERE  OWNER        = 'MCP_APP'
          AND  OBJECT_NAME  = :1
          AND  PROCEDURE_NAME IS NOT NULL
        ORDER BY PROCEDURE_NAME
    """
    try:
        rows = await _exec(sql, [pkg_upper])
        await log_audit(_TOOL, _PKG, "LIST_PACKAGE_PROCEDURES", "READ",
                        {"package_name": package_name}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, _PKG, "LIST_PACKAGE_PROCEDURES", "READ",
                        {"package_name": package_name}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L5: get_procedure_signature ───────────────────────────────────────────────

async def get_procedure_signature(package_name: str, procedure_name: str) -> dict:
    pkg_upper = package_name.upper()
    proc_upper = procedure_name.upper()
    sql = """
        SELECT ARGUMENT_NAME, POSITION, IN_OUT, DATA_TYPE, DEFAULT_VALUE
        FROM   ALL_ARGUMENTS
        WHERE  OWNER         = 'MCP_APP'
          AND  PACKAGE_NAME  = :1
          AND  OBJECT_NAME   = :2
        ORDER BY POSITION
    """
    try:
        rows = await _exec(sql, [pkg_upper, proc_upper])
        payload = {"package_name": pkg_upper, "procedure_name": proc_upper}
        await log_audit(_TOOL, _PKG, "GET_PACKAGE_ARGUMENTS", "READ",
                        payload, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, _PKG, "GET_PACKAGE_ARGUMENTS", "READ",
                        {"package_name": package_name, "procedure_name": procedure_name},
                        "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L6: list_sequences ────────────────────────────────────────────────────────

async def list_sequences() -> dict:
    sql = """
        SELECT SEQUENCE_NAME, MIN_VALUE, MAX_VALUE,
               INCREMENT_BY, LAST_NUMBER
        FROM   ALL_SEQUENCES
        WHERE  SEQUENCE_OWNER = 'MCP_APP'
        ORDER BY SEQUENCE_NAME
    """
    try:
        rows = await _exec(sql)
        await log_audit(_TOOL, "", "list_sequences", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "list_sequences", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L7: list_indexes ──────────────────────────────────────────────────────────

async def list_indexes(table_name: str | None = None) -> dict:
    if table_name:
        sql = """
            SELECT ai.INDEX_NAME, ai.TABLE_NAME, ai.UNIQUENESS,
                   aic.COLUMN_NAME, ai.INDEX_TYPE
            FROM   ALL_INDEXES     ai
            JOIN   ALL_IND_COLUMNS aic
                   ON aic.INDEX_NAME  = ai.INDEX_NAME
                  AND aic.TABLE_OWNER = ai.OWNER
            WHERE  ai.OWNER      = 'MCP_APP'
              AND  ai.TABLE_NAME = UPPER(:1)
            ORDER BY ai.INDEX_NAME, aic.COLUMN_POSITION
        """
        params = [table_name]
    else:
        sql = """
            SELECT ai.INDEX_NAME, ai.TABLE_NAME, ai.UNIQUENESS,
                   aic.COLUMN_NAME, ai.INDEX_TYPE
            FROM   ALL_INDEXES     ai
            JOIN   ALL_IND_COLUMNS aic
                   ON aic.INDEX_NAME  = ai.INDEX_NAME
                  AND aic.TABLE_OWNER = ai.OWNER
            WHERE  ai.OWNER = 'MCP_APP'
            ORDER BY ai.TABLE_NAME, ai.INDEX_NAME, aic.COLUMN_POSITION
        """
        params = []
    try:
        rows = await _exec(sql, params)
        await log_audit(_TOOL, "", "list_indexes", "READ",
                        {"table_name": table_name}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "list_indexes", "READ",
                        {"table_name": table_name}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── L8: find_procedure_for_table ─────────────────────────────────────────────

async def find_procedure_for_table(table_name: str) -> dict:
    sql = """
        SELECT NAME AS object_name, TYPE AS object_type, LINE AS line_number, TEXT AS source_line
        FROM   ALL_SOURCE
        WHERE  OWNER = 'MCP_APP'
          AND  UPPER(TEXT) LIKE UPPER('%' || :1 || '%')
          AND  TYPE IN ('PACKAGE', 'PACKAGE BODY', 'PROCEDURE', 'FUNCTION')
        ORDER BY NAME, LINE
    """
    try:
        rows = await _exec(sql, [table_name])
        await log_audit(_TOOL, "", "find_procedure_for_table", "READ",
                        {"table_name": table_name}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "find_procedure_for_table", "READ",
                        {"table_name": table_name}, "ERROR", str(exc))
        return map_oracle_error(exc)
