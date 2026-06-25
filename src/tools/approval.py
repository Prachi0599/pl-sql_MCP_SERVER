"""Group K — Audit & Approval Workflow Engine.

Public tools:
  get_pending_approvals, get_my_pending_requests,
  get_audit_log, get_audit_stats,
  approve_request, reject_request

Internal helper (imported by all write tools):
  create_approval_request(conn, package_name, procedure_name,
                          action_type, old_value, new_value, requested_by)
  -> {"request_id": N, "status": "PENDING", ...}

NEW_VALUE JSON stored in MCP_APPROVAL_REQUEST:
  {"params": [positional_arg1, positional_arg2, ...]}
"""
from __future__ import annotations

import json
from typing import Any

import oracledb

from src.db.pool import get_connection
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "approval"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500


# ── shared DB helpers ─────────────────────────────────────────────────────────

async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


async def _callproc(conn: oracledb.AsyncConnection,
                    proc_name: str, args: list) -> None:
    with conn.cursor() as cur:
        await cur.callproc(proc_name, args)


async def _exec_dml(conn: oracledb.AsyncConnection,
                    sql: str, params: list | None = None) -> int:
    """Execute INSERT/UPDATE/DELETE or PL/SQL block — no result set.

    Returns the number of rows affected (cur.rowcount). For anonymous PL/SQL
    blocks Oracle reports the rowcount of the last DML run inside the block."""
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        return cur.rowcount or 0


def _clamp(n: int) -> int:
    return min(max(1, n), _LIMIT_MAX)


def _ok(data: Any, row_count: int | None = None) -> dict:
    r: dict = {"success": True, "data": data}
    if row_count is not None:
        r["row_count"] = row_count
    return r


# ── DML dispatcher ────────────────────────────────────────────────────────────

async def _dispatch_dml(conn: oracledb.AsyncConnection,
                        package_name: str | None,
                        procedure_name: str | None,
                        new_value_json: str | None) -> dict:
    """Parse NEW_VALUE JSON and execute the stored DML action.

    NEW_VALUE formats:
      Package proc:  {"params": [arg1, ...]}
      Direct SQL:    {"sql": "INSERT/UPDATE ...", "params": [...]}  ← package_name="DIRECT_SQL"
      Multi-SQL:     {"statements": [{"sql": ..., "params": ...}, ...]}  ← package_name="DIRECT_SQL"
      Optional:      Append "post_query": {"sql": ..., "params": [...]} to any format
                     — result available in return["post_query_result"]
    """
    try:
        payload = json.loads(new_value_json or "{}")
    except (json.JSONDecodeError, AttributeError):
        payload = {}

    params = payload.get("params", [])
    rows_affected = 0

    if package_name == "DIRECT_SQL":
        statements = payload.get("statements")
        if statements:
            for stmt in statements:
                rows_affected += await _exec_dml(conn, stmt["sql"], stmt.get("params", []))
        elif "sql" in payload:
            rows_affected += await _exec_dml(conn, payload["sql"], params)
        else:
            return {"dispatched": False, "reason": "No SQL in DIRECT_SQL payload"}
        await conn.commit()
        result: dict = {"dispatched": True, "method": "direct_sql",
                        "rows_affected": rows_affected}
    else:
        if not procedure_name:
            return {"dispatched": False, "reason": "No procedure in approval request"}
        full_proc = (
            f"{package_name}.{procedure_name}" if package_name else procedure_name
        )
        await _callproc(conn, full_proc, params)
        await conn.commit()
        # A package procedure performs its own DML internally; oracledb cannot
        # report its rowcount, so we report 1 (the single entity it acts on).
        rows_affected = 1
        result = {"dispatched": True, "procedure": full_proc,
                  "rows_affected": rows_affected}

    post_query = payload.get("post_query")
    if post_query:
        rows = await _exec(conn, post_query["sql"], post_query.get("params", []))
        result["post_query_result"] = rows[0] if rows else {}

    return result


# DBA maintenance procedures whose effect is NOT measured in rows (DDL / DBMS_STATS
# / recompiles). For these, "0 rows changed" is meaningless, so we describe the
# action performed instead, naming the target from the OLD_VALUE JSON.
_MAINTENANCE = {
    "GATHER_TABLE_STATS": ("gathered optimizer statistics for", "table_name"),
    "REBUILD_INDEX":      ("rebuilt index", "index_name"),
    "RECOMPILE_OBJECT":   ("recompiled", "object_name"),
    "DROP_INDEX":         ("dropped index", "index_name"),
}


def _describe_change(action_type: str | None,
                     old_value_json: str | None,
                     new_value_json: str | None,
                     procedure_name: str | None,
                     rows_affected: int) -> str:
    """Build one human-readable sentence describing what an approved change did,
    INCLUDING the row count where that is meaningful (so callers should not
    re-state the row count separately).

    Examples:
      "update account status: 'ACTIVE' -> 'INACTIVE' (1 row changed)"
      "insert currency: created 1 row"
      "gathered optimizer statistics for CUSTOMER"     (no row count — maintenance)
    """
    act = (action_type or "CHANGE").upper()
    noun = "row" if rows_affected == 1 else "rows"

    old: dict = {}
    try:
        old = json.loads(old_value_json) if old_value_json else {}
    except (json.JSONDecodeError, TypeError):
        old = {}

    # DBA maintenance: name the action + target, no row count.
    proc = (procedure_name or "").upper()
    if proc in _MAINTENANCE:
        verb, target_key = _MAINTENANCE[proc]
        target = old.get(target_key) if isinstance(old, dict) else None
        return f"{verb} {target}".strip() if target else verb

    # Find the human before/after values in OLD_VALUE. Tools store the prior value
    # as {"old_<thing>": X} and (where known) the target as {"new_<thing>": Y}.
    # We deliberately do NOT guess the "after" from the SQL bind params — those are
    # numeric IDs (e.g. currency_id / account_id), which produced wrong summaries
    # like 'INR' -> '122'.
    before = after = None
    for k, v in (old.items() if isinstance(old, dict) else []):
        if before is None and k.startswith("old_"):
            before = v
        elif after is None and k.startswith("new_"):
            after = v

    label = (procedure_name or act).replace("_", " ").lower()

    if act == "UPDATE":
        if before is not None and after is not None:
            return f"{label}: '{before}' -> '{after}' ({rows_affected} {noun} changed)"
        if before is not None:
            return f"{label}: was '{before}' ({rows_affected} {noun} changed)"
        return f"{label}: {rows_affected} {noun} updated"
    if act == "INSERT":
        return f"{label}: created {rows_affected} {noun}"
    if act == "DELETE":
        return f"{label}: deleted {rows_affected} {noun}"
    return f"{label}: {rows_affected} {noun} affected"


def _past_change_phrase(action_type: str | None,
                        old_value_json: str | None,
                        procedure_name: str | None) -> str:
    """Human phrase for an ALREADY-applied change (no row count available),
    reusing the same OLD_VALUE old_*/new_* convention as _describe_change."""
    act = (action_type or "CHANGE").upper()
    try:
        old = json.loads(old_value_json) if old_value_json else {}
    except (json.JSONDecodeError, TypeError):
        old = {}
    old = old if isinstance(old, dict) else {}

    proc = (procedure_name or "").upper()
    if proc in _MAINTENANCE:
        verb, key = _MAINTENANCE[proc]
        target = old.get(key)
        return f"{verb} {target}".strip() if target else verb

    before = after = None
    for k, v in old.items():
        if before is None and k.startswith("old_"):
            before = v
        elif after is None and k.startswith("new_"):
            after = v
    label = (procedure_name or act).replace("_", " ").lower()
    if act == "UPDATE":
        if before is not None and after is not None:
            return f"{label}: '{before}' -> '{after}'"
        if before is not None:
            return f"{label}: was '{before}'"
    return label


async def get_recent_changes(limit: int = 10) -> dict:
    """Return the most recently APPROVED (applied) changes from the approval
    history, newest first, each with a human-readable summary. This is the
    cross-session source for 'what changes have been made'."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT REQUEST_ID, PACKAGE_NAME, PROCEDURE_NAME, ACTION_TYPE,
                   OLD_VALUE, APPROVED_BY,
                   TO_CHAR(APPROVED_DTM, 'YYYY-MM-DD HH24:MI') AS approved_dtm
            FROM   MCP_APP.MCP_APPROVAL_REQUEST
            WHERE  STATUS = 'APPROVED'
            ORDER BY APPROVED_DTM DESC NULLS LAST, REQUEST_ID DESC
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        changes = [{
            "request_id": r["request_id"],
            "summary": _past_change_phrase(
                r["action_type"], r.get("old_value"), r.get("procedure_name")),
            "action_type": r["action_type"],
            "approved_by": r.get("approved_by"),
            "approved_dtm": r.get("approved_dtm"),
        } for r in rows]
        await log_audit(_TOOL, "", "get_recent_changes", "READ", {}, "SUCCESS")
        return _ok(changes, len(changes))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_recent_changes", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Internal helper used by all write tools ───────────────────────────────────

async def create_approval_request(
    conn: oracledb.AsyncConnection,
    package_name: str,
    procedure_name: str,
    action_type: str,
    old_value: str | None,
    new_value: str,
    requested_by: str = "mcp_user",
) -> dict:
    """
    Calls MCP_SECURITY_PKG.CREATE_APPROVAL_REQUEST, then queries the newest
    PENDING row for this user to retrieve the generated REQUEST_ID.
    Returns {"request_id": N, "status": "PENDING", "summary": ...}.
    """
    await _callproc(conn, "MCP_SECURITY_PKG.CREATE_APPROVAL_REQUEST", [
        package_name, procedure_name, action_type,
        old_value or "", new_value, requested_by,
    ])

    rows = await _exec(conn, """
        SELECT REQUEST_ID FROM MCP_APPROVAL_REQUEST
        WHERE  UPPER(REQUESTED_BY) = UPPER(:1)
          AND  STATUS = 'PENDING'
        ORDER BY REQUEST_ID DESC
        FETCH FIRST 1 ROW ONLY
    """, [requested_by])

    request_id = rows[0]["request_id"] if rows else None
    return {
        "request_id": request_id,
        "status": "PENDING",
        "package_name": package_name,
        "procedure_name": procedure_name,
        "action_type": action_type,
        "summary": (
            f"Pending approval: {package_name}.{procedure_name} "
            f"({action_type}) — request #{request_id}"
        ),
    }


# ── K1: get_pending_approvals ─────────────────────────────────────────────────

async def get_pending_approvals(requested_by: str | None = None,
                                 limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = []
    by_clause = ""
    if requested_by:
        by_clause = "AND UPPER(REQUESTED_BY) = UPPER(:1)"
        params.append(requested_by)
    params.append(limit)
    lim_pos = len(params)
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT REQUEST_ID, PACKAGE_NAME, PROCEDURE_NAME, ACTION_TYPE,
                   STATUS, REQUESTED_BY, APPROVED_BY, CREATED_DTM, APPROVED_DTM,
                   NEW_VALUE
            FROM   MCP_APP.MCP_APPROVAL_REQUEST
            WHERE  STATUS = 'PENDING'
            {by_clause}
            ORDER BY CREATED_DTM DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_pending_approvals", "READ",
                        {"requested_by": requested_by}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_pending_approvals", "READ",
                        {"requested_by": requested_by}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── K2: get_my_pending_requests ───────────────────────────────────────────────

async def get_my_pending_requests(requested_by: str,
                                   limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT REQUEST_ID, PACKAGE_NAME, PROCEDURE_NAME, ACTION_TYPE,
                   STATUS, REQUESTED_BY, APPROVED_BY, CREATED_DTM, APPROVED_DTM,
                   NEW_VALUE
            FROM   MCP_APP.MCP_APPROVAL_REQUEST
            WHERE  STATUS = 'PENDING'
              AND  UPPER(REQUESTED_BY) = UPPER(:1)
            ORDER BY CREATED_DTM DESC
            FETCH FIRST :2 ROWS ONLY
        """, [requested_by, limit])
        await log_audit(_TOOL, "", "get_my_pending_requests", "READ",
                        {"requested_by": requested_by}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_my_pending_requests", "READ",
                        {"requested_by": requested_by}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── K3: get_audit_log ─────────────────────────────────────────────────────────

async def get_audit_log(tool_name: str | None = None,
                         status: str | None = None,
                         limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = []
    clauses: list[str] = []
    p = 1
    if tool_name:
        clauses.append(f"AND UPPER(TOOL_NAME) = UPPER(:{p})")
        params.append(tool_name)
        p += 1
    if status:
        clauses.append(f"AND UPPER(STATUS) = UPPER(:{p})")
        params.append(status)
        p += 1
    params.append(limit)
    lim_pos = p
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT AUDIT_ID, TOOL_NAME, PACKAGE_NAME, PROCEDURE_NAME,
                   ACTION_TYPE, STATUS, ERROR_MESSAGE, CREATED_BY, CREATED_DTM
            FROM   MCP_APP.MCP_AUDIT_LOG
            WHERE  1=1 {"".join(clauses)}
            ORDER BY CREATED_DTM DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_audit_log", "READ",
                        {"tool_name": tool_name, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_audit_log", "READ",
                        {"tool_name": tool_name}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── K4: get_audit_stats ───────────────────────────────────────────────────────

async def get_audit_stats() -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT TOOL_NAME,
                   COUNT(*)                           AS total_calls,
                   SUM(CASE WHEN STATUS='SUCCESS' THEN 1 ELSE 0 END) AS success_count,
                   SUM(CASE WHEN STATUS='ERROR'   THEN 1 ELSE 0 END) AS error_count,
                   MIN(CREATED_DTM) AS first_call_dtm,
                   MAX(CREATED_DTM) AS last_call_dtm
            FROM   MCP_APP.MCP_AUDIT_LOG
            GROUP BY TOOL_NAME
            ORDER BY total_calls DESC
        """)
        await log_audit(_TOOL, "", "get_audit_stats", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_audit_stats", "READ",
                        {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── K5: approve_request ───────────────────────────────────────────────────────

async def approve_request(request_id: int, approved_by: str) -> dict:
    """
    1. Read MCP_APPROVAL_REQUEST row (get NEW_VALUE for DML dispatch).
    2. Call MCP_SECURITY_PKG.APPROVE_REQUEST — raises ORA-20001/20002 on error.
    3. Dispatch the stored DML using _dispatch_dml.
    4. Return success with request details.
    Audit log written with ACTION_TYPE='UPDATE'.
    """
    conn = await get_connection()
    try:
        # Read request row to get DML details
        rows = await _exec(conn, """
            SELECT REQUEST_ID, PACKAGE_NAME, PROCEDURE_NAME,
                   ACTION_TYPE, OLD_VALUE, NEW_VALUE, STATUS
            FROM   MCP_APP.MCP_APPROVAL_REQUEST
            WHERE  REQUEST_ID = :1
        """, [request_id])

        if not rows:
            return {"success": False, "error_code": "ORA-20002",
                    "message": f"Approval request {request_id} not found"}

        req = rows[0]
        if req["status"] != "PENDING":
            return {"success": False, "error_code": "ORA-20001",
                    "message": (f"Request {request_id} cannot be approved — "
                                f"current status: {req['status']}")}

        # Mark as APPROVED (Oracle raises ORA-20001/20002 on violation)
        await _callproc(conn, "MCP_SECURITY_PKG.APPROVE_REQUEST",
                        [request_id, approved_by])

        # Execute the actual DML
        dml = await _dispatch_dml(
            conn,
            req.get("package_name"),
            req.get("procedure_name"),
            req.get("new_value"),
        )

        rows_affected = dml.get("rows_affected", 0) if isinstance(dml, dict) else 0
        change_summary = _describe_change(
            req.get("action_type"), req.get("old_value"), req.get("new_value"),
            req.get("procedure_name"), rows_affected)

        await log_audit(_TOOL, "MCP_SECURITY_PKG", "APPROVE_REQUEST",
                        "UPDATE",
                        {"request_id": request_id, "approved_by": approved_by,
                         "rows_affected": rows_affected},
                        "SUCCESS")
        return {
            "success": True,
            "request_id": request_id,
            "approved_by": approved_by,
            "status": "APPROVED",
            "action_type": req.get("action_type"),
            "rows_affected": rows_affected,
            "change_summary": change_summary,
            "dml_result": dml,
        }
    except oracledb.DatabaseError as exc:
        err = map_oracle_error(exc)
        await log_audit(_TOOL, "MCP_SECURITY_PKG", "APPROVE_REQUEST",
                        "UPDATE",
                        {"request_id": request_id}, "ERROR", err["message"])
        return err
    except Exception as exc:
        await log_audit(_TOOL, "MCP_SECURITY_PKG", "APPROVE_REQUEST",
                        "UPDATE",
                        {"request_id": request_id}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── K6: reject_request ────────────────────────────────────────────────────────

async def reject_request(request_id: int,
                          rejected_by: str,
                          reason: str = "") -> dict:
    """
    Calls MCP_SECURITY_PKG.REJECT_REQUEST — sets STATUS='REJECTED'.
    Target table is never touched (no DML dispatch).
    """
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT STATUS FROM MCP_APP.MCP_APPROVAL_REQUEST
            WHERE REQUEST_ID = :1
        """, [request_id])

        if not rows:
            return {"success": False, "error_code": "ORA-20002",
                    "message": f"Approval request {request_id} not found"}

        if rows[0]["status"] != "PENDING":
            return {"success": False, "error_code": "ORA-20001",
                    "message": (f"Request {request_id} cannot be rejected — "
                                f"current status: {rows[0]['status']}")}

        await _callproc(conn, "MCP_SECURITY_PKG.REJECT_REQUEST",
                        [request_id, rejected_by, reason or "No reason given"])

        await log_audit(_TOOL, "MCP_SECURITY_PKG", "REJECT_REQUEST",
                        "UPDATE",
                        {"request_id": request_id, "rejected_by": rejected_by,
                         "reason": reason},
                        "SUCCESS")
        return {
            "success": True,
            "request_id": request_id,
            "rejected_by": rejected_by,
            "status": "REJECTED",
            "reason": reason,
        }
    except oracledb.DatabaseError as exc:
        err = map_oracle_error(exc)
        await log_audit(_TOOL, "MCP_SECURITY_PKG", "REJECT_REQUEST",
                        "UPDATE",
                        {"request_id": request_id}, "ERROR", err["message"])
        return err
    except Exception as exc:
        await log_audit(_TOOL, "MCP_SECURITY_PKG", "REJECT_REQUEST",
                        "UPDATE",
                        {"request_id": request_id}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
