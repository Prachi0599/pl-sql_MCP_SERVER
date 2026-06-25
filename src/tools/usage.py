"""Groups G, H, I (read side) — Usage Analytics & Operations Read Tools.

Group G: get_events_by_account, get_event_summary, get_top_usage_accounts,
         get_events_by_source_system, get_bandwidth_trend,
         get_failed_events, get_usage_anomalies
Group H: get_load_status_today, get_missing_loads,
         get_load_history, get_failed_load_summary
Group I: get_open_requests, get_requests_by_customer
"""
from __future__ import annotations

from datetime import date
from typing import Any

import oracledb

from src.db.pool import get_connection
from src.db.resolvers import resolve_account_number, resolve_customer_number
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "usage"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500

_GRANULARITY_MAP = {
    "DAY":   ("TRUNC(EVENT_DTM)",       "'YYYY-MM-DD'"),
    "MONTH": ("TRUNC(EVENT_DTM, 'MM')", "'YYYY-MM'"),
}


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


async def _callfunc_cursor(conn: oracledb.AsyncConnection,
                           func_name: str, args: list) -> list[dict]:
    with conn.cursor() as cur:
        ref_cur = await cur.callfunc(func_name, oracledb.DB_TYPE_CURSOR, args)
    cols = [d[0].lower() for d in ref_cur.description]
    rows = await ref_cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _clamp(n: int) -> int:
    return min(max(1, n), _LIMIT_MAX)


def _ok(data: Any, row_count: int | None = None) -> dict:
    r: dict = {"success": True, "data": data}
    if row_count is not None:
        r["row_count"] = row_count
    return r


# ── G1: get_events_by_account ─────────────────────────────────────────────────

async def get_events_by_account(account_number: str,
                                 date_from: str | None = None,
                                 date_to: str | None = None,
                                 limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)

        if date_from or date_to:
            # Direct SQL path — supports TIMESTAMP bind variables (T09-02)
            params: list = [account_id]
            clauses: list[str] = []
            p = 2
            if date_from:
                clauses.append(
                    f"AND EVENT_DTM >= TO_TIMESTAMP(:{p}, 'YYYY-MM-DD')")
                params.append(date_from)
                p += 1
            if date_to:
                clauses.append(
                    f"AND EVENT_DTM < TO_TIMESTAMP(:{p}, 'YYYY-MM-DD')"
                    " + INTERVAL '1' DAY")
                params.append(date_to)
                p += 1
            params.append(limit)
            rows = await _exec(conn, f"""
                SELECT EVENT_ID, ACCOUNT_ID, ACCOUNT_NUM, EVENT_DTM,
                       CREATED_DTM, IN_BITS, OUT_BITS, SPEED_MBPS,
                       BANDWIDTH_MBPS, EVENT_TYPE, SOURCE_SYSTEM, STATUS
                FROM   MCP_APP.COSTED_EVENT
                WHERE  ACCOUNT_ID = :1
                {"".join(clauses)}
                ORDER BY EVENT_DTM DESC
                FETCH FIRST :{p} ROWS ONLY
            """, params)
        else:
            # Package path (T09-01) — account resolved before calling
            try:
                rows = await _callfunc_cursor(
                    conn, "USAGE_ANALYTICS_PKG.GET_ACCOUNT_USAGE", [account_id])
                rows = rows[:limit]
            except Exception:
                rows = await _exec(conn, """
                    SELECT EVENT_ID, ACCOUNT_ID, ACCOUNT_NUM, EVENT_DTM,
                           CREATED_DTM, IN_BITS, OUT_BITS, SPEED_MBPS,
                           BANDWIDTH_MBPS, EVENT_TYPE, SOURCE_SYSTEM, STATUS
                    FROM   MCP_APP.COSTED_EVENT
                    WHERE  ACCOUNT_ID = :1
                    ORDER BY EVENT_DTM DESC
                    FETCH FIRST :2 ROWS ONLY
                """, [account_id, limit])

        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG", "GET_ACCOUNT_USAGE",
                        "READ", {"account_number": account_number}, "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG", "GET_ACCOUNT_USAGE",
                        "READ", {"account_number": account_number},
                        "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG", "GET_ACCOUNT_USAGE",
                        "READ", {"account_number": account_number},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G2: get_event_summary ─────────────────────────────────────────────────────

async def get_event_summary(account_number: str,
                             date_from: str | None = None,
                             date_to: str | None = None) -> dict:
    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        params: list = [account_id]
        clauses: list[str] = []
        p = 2
        if date_from:
            clauses.append(
                f"AND EVENT_DTM >= TO_TIMESTAMP(:{p}, 'YYYY-MM-DD')")
            params.append(date_from)
            p += 1
        if date_to:
            clauses.append(
                f"AND EVENT_DTM < TO_TIMESTAMP(:{p}, 'YYYY-MM-DD')"
                " + INTERVAL '1' DAY")
            params.append(date_to)
            p += 1
        rows = await _exec(conn, f"""
            SELECT COUNT(*)             AS event_count,
                   SUM(IN_BITS)         AS total_in_bits,
                   SUM(OUT_BITS)        AS total_out_bits,
                   ROUND(AVG(SPEED_MBPS), 2) AS avg_speed_mbps,
                   MAX(SPEED_MBPS)      AS max_speed_mbps,
                   MIN(EVENT_DTM)       AS earliest_event,
                   MAX(EVENT_DTM)       AS latest_event
            FROM   MCP_APP.COSTED_EVENT
            WHERE  ACCOUNT_ID = :1
            {"".join(clauses)}
        """, params)
        await log_audit(_TOOL, "", "get_event_summary", "READ",
                        {"account_number": account_number}, "SUCCESS")
        return _ok(rows[0] if rows else None, 1 if rows else 0)
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_event_summary", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_event_summary", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G3: get_top_usage_accounts ────────────────────────────────────────────────

async def get_top_usage_accounts(limit: int = 10) -> dict:
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "USAGE_ANALYTICS_PKG.GET_TOP_BANDWIDTH_ACCOUNTS",
                [limit])
        except Exception:
            rows = await _exec(conn, """
                SELECT a.ACCOUNT_NUMBER, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                       SUM(e.IN_BITS + e.OUT_BITS)   AS total_bits,
                       ROUND(AVG(e.SPEED_MBPS), 2)   AS avg_speed_mbps,
                       MAX(e.BANDWIDTH_MBPS)          AS peak_bandwidth_mbps,
                       COUNT(e.EVENT_ID)              AS event_count
                FROM   MCP_APP.COSTED_EVENT e
                JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = e.ACCOUNT_ID
                JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
                GROUP BY a.ACCOUNT_NUMBER, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME
                ORDER BY total_bits DESC
                FETCH FIRST :1 ROWS ONLY
            """, [limit])
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG",
                        "GET_TOP_BANDWIDTH_ACCOUNTS", "READ",
                        {"limit": limit}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG",
                        "GET_TOP_BANDWIDTH_ACCOUNTS", "READ",
                        {"limit": limit}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G4: get_events_by_source_system ──────────────────────────────────────────

async def get_events_by_source_system(source_system: str,
                                       status: str | None = None,
                                       limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = [source_system]
    status_clause = ""
    if status:
        status_clause = "AND UPPER(STATUS) = UPPER(:2)"
        params.append(status)
    params.append(limit)
    lim_pos = len(params)
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT EVENT_ID, ACCOUNT_ID, ACCOUNT_NUM, EVENT_DTM,
                   IN_BITS, OUT_BITS, SPEED_MBPS, BANDWIDTH_MBPS,
                   EVENT_TYPE, SOURCE_SYSTEM, STATUS
            FROM   MCP_APP.COSTED_EVENT
            WHERE  UPPER(SOURCE_SYSTEM) = UPPER(:1)
            {status_clause}
            ORDER BY EVENT_DTM DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_events_by_source_system", "READ",
                        {"source_system": source_system, "status": status},
                        "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_events_by_source_system", "READ",
                        {"source_system": source_system}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G5: get_bandwidth_trend ───────────────────────────────────────────────────

async def get_bandwidth_trend(account_number: str | None = None,
                               granularity: str = "DAY",
                               limit: int = 30) -> dict:
    limit = _clamp(limit)
    gran_upper = granularity.upper()
    if gran_upper not in _GRANULARITY_MAP:
        return {"success": False, "error_code": "INVALID_INPUT",
                "message": f"granularity must be DAY or MONTH, got '{granularity}'"}

    trunc_expr, fmt = _GRANULARITY_MAP[gran_upper]
    params: list = []
    acct_clause = ""
    p = 1
    if account_number:
        acct_clause = f"WHERE ACCOUNT_ID = (SELECT ACCOUNT_ID FROM MCP_APP.ACCOUNT WHERE UPPER(ACCOUNT_NUMBER) = UPPER(:{p}))"
        params.append(account_number)
        p += 1
    params.append(limit)
    lim_pos = p

    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT TO_CHAR({trunc_expr}, {fmt})        AS period,
                   SUM(IN_BITS)                        AS total_in_bits,
                   SUM(OUT_BITS)                       AS total_out_bits,
                   ROUND(AVG(SPEED_MBPS), 2)           AS avg_speed_mbps,
                   COUNT(EVENT_ID)                     AS event_count
            FROM   MCP_APP.COSTED_EVENT
            {acct_clause}
            GROUP BY {trunc_expr}
            ORDER BY {trunc_expr} DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_bandwidth_trend", "READ",
                        {"account_number": account_number,
                         "granularity": granularity}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_bandwidth_trend", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G6: get_failed_events ─────────────────────────────────────────────────────

async def get_failed_events(source_system: str | None = None,
                             limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = []
    sys_clause = ""
    p = 1
    if source_system:
        sys_clause = f"AND UPPER(SOURCE_SYSTEM) = UPPER(:{p})"
        params.append(source_system)
        p += 1
    params.append(limit)
    lim_pos = p
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT EVENT_ID, ACCOUNT_NUM, EVENT_DTM, IN_BITS, OUT_BITS,
                   SPEED_MBPS, EVENT_TYPE, SOURCE_SYSTEM, STATUS
            FROM   MCP_APP.COSTED_EVENT
            WHERE  STATUS != 'SUCCESS'
            {sys_clause}
            ORDER BY EVENT_DTM DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_failed_events", "READ",
                        {"source_system": source_system}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_failed_events", "READ",
                        {"source_system": source_system}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── G7: get_usage_anomalies ───────────────────────────────────────────────────

async def get_usage_anomalies(threshold_mbps: float = 100.0) -> dict:
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "USAGE_ANALYTICS_PKG.GET_USAGE_ANOMALIES",
                [threshold_mbps])
        except Exception:
            rows = await _exec(conn, """
                SELECT e.EVENT_ID, e.ACCOUNT_NUM, e.EVENT_DTM,
                       e.SPEED_MBPS, e.BANDWIDTH_MBPS, e.SOURCE_SYSTEM,
                       a.ACCOUNT_NUMBER, c.CUSTOMER_NUMBER
                FROM   MCP_APP.COSTED_EVENT e
                JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = e.ACCOUNT_ID
                JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
                WHERE  e.SPEED_MBPS > :1
                ORDER BY e.SPEED_MBPS DESC
            """, [threshold_mbps])
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG", "GET_USAGE_ANOMALIES",
                        "READ", {"threshold_mbps": threshold_mbps}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "USAGE_ANALYTICS_PKG", "GET_USAGE_ANOMALIES",
                        "READ", {"threshold_mbps": threshold_mbps},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── H1: get_load_status_today ─────────────────────────────────────────────────

async def get_load_status_today() -> dict:
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "LOAD_MONITOR_PKG.GET_LOAD_STATUS", [date.today()])
        except Exception:
            rows = await _exec(conn, """
                SELECT LOAD_ID, SOURCE_SYSTEM, RECORDS_RECEIVED,
                       RECORDS_LOADED, RECORDS_FAILED, STATUS,
                       ERROR_SUMMARY, LOAD_START_DTM, LOAD_END_DTM
                FROM   MCP_APP.DAILY_LOAD_LOG
                WHERE  TRUNC(LOAD_DATE) = TRUNC(SYSDATE)
                ORDER BY SOURCE_SYSTEM
            """)
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_LOAD_STATUS",
                        "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_LOAD_STATUS",
                        "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── H2: get_missing_loads ─────────────────────────────────────────────────────

async def get_missing_loads(days_back: int = 7) -> dict:
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "LOAD_MONITOR_PKG.GET_MISSING_LOADS", [days_back])
        except Exception:
            rows = await _exec(conn, """
                SELECT DISTINCT SOURCE_SYSTEM,
                       MAX(LOAD_DATE) AS last_load_date,
                       ROUND(SYSDATE - MAX(LOAD_DATE)) AS days_since_last_load
                FROM   MCP_APP.DAILY_LOAD_LOG
                WHERE  LOAD_DATE >= TRUNC(SYSDATE) - :1
                GROUP BY SOURCE_SYSTEM
                HAVING MAX(LOAD_DATE) < TRUNC(SYSDATE)
                ORDER BY days_since_last_load DESC
            """, [days_back])
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_MISSING_LOADS",
                        "READ", {"days_back": days_back}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_MISSING_LOADS",
                        "READ", {"days_back": days_back}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── H3: get_load_history ─────────────────────────────────────────────────────

async def get_load_history(source_system: str, days_back: int = 30) -> dict:
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "LOAD_MONITOR_PKG.GET_LOAD_HISTORY",
                [source_system, days_back])
        except Exception:
            rows = await _exec(conn, """
                SELECT LOAD_ID, LOAD_DATE, SOURCE_SYSTEM,
                       RECORDS_RECEIVED, RECORDS_LOADED, RECORDS_FAILED,
                       STATUS, ERROR_SUMMARY, LOAD_START_DTM, LOAD_END_DTM
                FROM   MCP_APP.DAILY_LOAD_LOG
                WHERE  UPPER(SOURCE_SYSTEM) = UPPER(:1)
                  AND  LOAD_DATE >= TRUNC(SYSDATE) - :2
                ORDER BY LOAD_DATE DESC
            """, [source_system, days_back])
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_LOAD_HISTORY",
                        "READ", {"source_system": source_system,
                                 "days_back": days_back}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_LOAD_HISTORY",
                        "READ", {"source_system": source_system},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── H4: get_failed_load_summary ───────────────────────────────────────────────

async def get_failed_load_summary(days_back: int = 7) -> dict:
    conn = await get_connection()
    try:
        try:
            rows = await _callfunc_cursor(
                conn, "LOAD_MONITOR_PKG.GET_FAILED_LOAD_SUMMARY", [days_back])
        except Exception:
            rows = await _exec(conn, """
                SELECT SOURCE_SYSTEM,
                       COUNT(*)                          AS failed_loads,
                       SUM(RECORDS_FAILED)               AS total_records_failed,
                       MAX(LOAD_DATE)                    AS last_failure_date,
                       LISTAGG(SUBSTR(ERROR_SUMMARY, 1, 100), ' | ')
                           WITHIN GROUP (ORDER BY LOAD_DATE DESC) AS error_samples
                FROM   MCP_APP.DAILY_LOAD_LOG
                WHERE  STATUS = 'FAILED'
                  AND  LOAD_DATE >= TRUNC(SYSDATE) - :1
                GROUP BY SOURCE_SYSTEM
                ORDER BY failed_loads DESC
            """, [days_back])
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_FAILED_LOAD_SUMMARY",
                        "READ", {"days_back": days_back}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "LOAD_MONITOR_PKG", "GET_FAILED_LOAD_SUMMARY",
                        "READ", {"days_back": days_back}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── I1: get_open_requests ─────────────────────────────────────────────────────

async def get_open_requests(assigned_to: str | None = None) -> dict:
    # Use an explicit SELECT (not the PL/SQL function) so every useful field is
    # always present: description, who raised it (created_by), who it is assigned
    # to, resolution notes, plus the customer name/number for context.
    conn = await get_connection()
    try:
        params: list = []
        assign_clause = ""
        if assigned_to:
            assign_clause = "AND UPPER(sr.ASSIGNED_TO) = UPPER(:1)"
            params.append(assigned_to)
        rows = await _exec(conn, f"""
            SELECT sr.REQUEST_ID, sr.REQUEST_TYPE, sr.PRIORITY, sr.STATUS,
                   sr.DESCRIPTION,
                   sr.RAISED_BY                         AS raised_by,
                   NVL(sr.ASSIGNED_TO, 'Unassigned')    AS assigned_to,
                   sr.RESOLUTION_NOTES,
                   c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   a.ACCOUNT_NUMBER,
                   TO_CHAR(sr.CREATED_DTM,  'YYYY-MM-DD HH24:MI') AS created_dtm,
                   TO_CHAR(sr.RESOLVED_DTM, 'YYYY-MM-DD HH24:MI') AS resolved_dtm
            FROM   MCP_APP.SERVICE_REQUEST sr
            LEFT JOIN MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = sr.CUSTOMER_ID
            LEFT JOIN MCP_APP.ACCOUNT  a ON a.ACCOUNT_ID  = sr.ACCOUNT_ID
            WHERE  sr.STATUS IN ('OPEN', 'IN_PROGRESS')
            {assign_clause}
            ORDER BY sr.PRIORITY DESC, sr.CREATED_DTM ASC
        """, params)
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG", "GET_OPEN_REQUESTS",
                        "READ", {"assigned_to": assigned_to}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG", "GET_OPEN_REQUESTS",
                        "READ", {"assigned_to": assigned_to},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── I2: get_requests_by_customer ─────────────────────────────────────────────

async def get_requests_by_customer(customer_number: str) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        rows = await _exec(conn, """
            SELECT sr.REQUEST_ID, sr.REQUEST_TYPE, sr.PRIORITY, sr.STATUS,
                   sr.DESCRIPTION,
                   sr.RAISED_BY                         AS raised_by,
                   NVL(sr.ASSIGNED_TO, 'Unassigned')    AS assigned_to,
                   sr.RESOLUTION_NOTES,
                   a.ACCOUNT_NUMBER,
                   TO_CHAR(sr.CREATED_DTM,  'YYYY-MM-DD HH24:MI') AS created_dtm,
                   TO_CHAR(sr.RESOLVED_DTM, 'YYYY-MM-DD HH24:MI') AS resolved_dtm
            FROM   MCP_APP.SERVICE_REQUEST sr
            LEFT JOIN MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = sr.ACCOUNT_ID
            WHERE  sr.CUSTOMER_ID = :1
            ORDER BY sr.CREATED_DTM DESC
        """, [cid])
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG",
                        "GET_REQUESTS_BY_CUSTOMER", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG",
                        "GET_REQUESTS_BY_CUSTOMER", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG",
                        "GET_REQUESTS_BY_CUSTOMER", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
