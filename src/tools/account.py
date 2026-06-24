"""Groups C & D (read side) — Address, Contact, Account Read Tools.

Group C: get_customer_addresses, get_customer_contacts, search_contacts_by_email
Group D: get_accounts_by_customer, get_account_details, get_accounts_by_currency,
         get_account_commissioning_info, get_accounts_by_billing_cycle,
         get_accounts_pending_termination
"""
from __future__ import annotations

from typing import Any

import oracledb

from src.db.pool import get_connection
from src.db.resolvers import resolve_customer_number, resolve_account_number
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "account"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _clamp(limit: int) -> int:
    return min(max(1, limit), _LIMIT_MAX)


def _ok(data: Any, row_count: int | None = None) -> dict:
    result: dict = {"success": True, "data": data}
    if row_count is not None:
        result["row_count"] = row_count
    return result


# ── C1: get_customer_addresses ────────────────────────────────────────────────

async def get_customer_addresses(customer_number: str) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        rows = await _exec(conn, """
            SELECT ADDRESS_ID, ADDRESS_TYPE, ADDRESS_LINE1,
                   CITY, STATE, COUNTRY, POSTAL_CODE
            FROM   MCP_APP.ADDRESS
            WHERE  CUSTOMER_ID = :1
            ORDER BY ADDRESS_TYPE
        """, [cid])
        await log_audit(_TOOL, "", "get_customer_addresses", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_customer_addresses", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_addresses", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── C2: get_customer_contacts ─────────────────────────────────────────────────

async def get_customer_contacts(customer_number: str) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        rows = await _exec(conn, """
            SELECT con.CONTACT_ID, con.CONTACT_NAME, con.DESIGNATION, con.EMAIL,
                   cd.PHONE_NUMBER, cd.ALTERNATE_EMAIL
            FROM   MCP_APP.CONTACT con
            LEFT JOIN MCP_APP.CONTACT_DETAILS cd
                   ON cd.CONTACT_ID = con.CONTACT_ID
            WHERE  con.CUSTOMER_ID = :1
            ORDER BY con.CONTACT_NAME
        """, [cid])
        await log_audit(_TOOL, "", "get_customer_contacts", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_customer_contacts", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_contacts", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── C3: search_contacts_by_email ──────────────────────────────────────────────

async def search_contacts_by_email(email_pattern: str,
                                   limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT con.CONTACT_ID, con.CONTACT_NAME, con.DESIGNATION,
                   con.EMAIL, cd.PHONE_NUMBER,
                   c.CUSTOMER_NUMBER, c.CUSTOMER_NAME
            FROM   MCP_APP.CONTACT con
            LEFT JOIN MCP_APP.CONTACT_DETAILS cd
                   ON cd.CONTACT_ID = con.CONTACT_ID
            JOIN   MCP_APP.CUSTOMER c
                   ON c.CUSTOMER_ID = con.CUSTOMER_ID
            WHERE  UPPER(con.EMAIL) LIKE UPPER('%' || :1 || '%')
            ORDER BY con.EMAIL
            FETCH FIRST :2 ROWS ONLY
        """, [email_pattern, limit])
        await log_audit(_TOOL, "", "search_contacts_by_email", "READ",
                        {"email_pattern": email_pattern}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "search_contacts_by_email", "READ",
                        {"email_pattern": email_pattern}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── D1: get_accounts_by_customer ──────────────────────────────────────────────

async def get_accounts_by_customer(customer_number: str,
                                   status: str | None = None) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        params: list = [cid]
        status_clause = ""
        if status:
            status_clause = "AND a.STATUS = UPPER(:2)"
            params.append(status)
        rows = await _exec(conn, f"""
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                   a.STATUS, a.BILLING_CYCLE, cur.CURRENCY_CODE,
                   ad.BILLABLE_FLAG, ad.COMMISSIONING_DATE, ad.TERMINATION_DATE
            FROM   MCP_APP.ACCOUNT a
            LEFT JOIN MCP_APP.CURRENCY cur
                   ON cur.CURRENCY_ID = a.CURRENCY_ID
            LEFT JOIN MCP_APP.ACCOUNT_DETAILS ad
                   ON ad.ACCOUNT_ID = a.ACCOUNT_ID
            WHERE  a.CUSTOMER_ID = :1
            {status_clause}
            ORDER BY a.ACCOUNT_NUMBER
        """, params)
        await log_audit(_TOOL, "", "get_accounts_by_customer", "READ",
                        {"customer_number": customer_number, "status": status},
                        "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_accounts_by_customer", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_accounts_by_customer", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── D2: get_account_details (calls ACCOUNT_PKG.GET_ACCOUNT_DETAILS) ──────────

async def get_account_details(account_number: str) -> dict:
    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        with conn.cursor() as cur:
            result_cursor = await cur.callfunc(
                "ACCOUNT_PKG.GET_ACCOUNT_DETAILS",
                oracledb.DB_TYPE_CURSOR,
                [account_id],
            )
        cols = [d[0].lower() for d in result_cursor.description]
        rows = await result_cursor.fetchall()
        data = [dict(zip(cols, row)) for row in rows]
        await log_audit(_TOOL, "ACCOUNT_PKG", "GET_ACCOUNT_DETAILS", "READ",
                        {"account_number": account_number}, "SUCCESS")
        return _ok(data[0] if data else None, len(data))
    except ValueError as exc:
        await log_audit(_TOOL, "ACCOUNT_PKG", "GET_ACCOUNT_DETAILS", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        # Fall back to direct SQL if package call fails
        try:
            rows = await _exec(conn, """
                SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                       a.STATUS, a.BILLING_CYCLE, cur.CURRENCY_CODE,
                       ad.BILLABLE_FLAG, ad.COMMISSIONING_DATE, ad.TERMINATION_DATE,
                       c.CUSTOMER_NUMBER
                FROM   MCP_APP.ACCOUNT a
                LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
                LEFT JOIN MCP_APP.ACCOUNT_DETAILS ad ON ad.ACCOUNT_ID = a.ACCOUNT_ID
                LEFT JOIN MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
                WHERE  UPPER(a.ACCOUNT_NUMBER) = UPPER(:1)
            """, [account_number])
            await log_audit(_TOOL, "ACCOUNT_PKG", "GET_ACCOUNT_DETAILS", "READ",
                            {"account_number": account_number}, "SUCCESS")
            return _ok(rows[0] if rows else None, len(rows))
        except Exception as exc2:
            await log_audit(_TOOL, "ACCOUNT_PKG", "GET_ACCOUNT_DETAILS", "READ",
                            {"account_number": account_number}, "ERROR", str(exc2))
            return map_oracle_error(exc2)
    finally:
        await conn.close()


# ── D3: get_accounts_by_currency ──────────────────────────────────────────────

async def get_accounts_by_currency(currency_code: str,
                                   status: str = "ACTIVE",
                                   limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = [currency_code]
    status_clause = ""
    if status and status.upper() != "ALL":
        status_clause = "AND a.STATUS = UPPER(:2)"
        params.append(status)
    params.append(limit)
    lim_pos = len(params)
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                   a.STATUS, a.BILLING_CYCLE, cur.CURRENCY_CODE,
                   c.CUSTOMER_NUMBER, c.CUSTOMER_NAME
            FROM   MCP_APP.ACCOUNT a
            JOIN   MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            WHERE  UPPER(cur.CURRENCY_CODE) = UPPER(:1)
              {status_clause}
            ORDER BY a.ACCOUNT_NUMBER
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_accounts_by_currency", "READ",
                        {"currency_code": currency_code, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_accounts_by_currency", "READ",
                        {"currency_code": currency_code}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── D4: get_account_commissioning_info ────────────────────────────────────────

async def get_account_commissioning_info(account_number: str) -> dict:
    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        rows = await _exec(conn, """
            SELECT a.ACCOUNT_NUMBER, a.STATUS, a.BILLING_CYCLE,
                   ad.BILLABLE_FLAG, ad.COMMISSIONING_DATE, ad.TERMINATION_DATE
            FROM   MCP_APP.ACCOUNT a
            LEFT JOIN MCP_APP.ACCOUNT_DETAILS ad ON ad.ACCOUNT_ID = a.ACCOUNT_ID
            WHERE  a.ACCOUNT_ID = :1
        """, [account_id])
        await log_audit(_TOOL, "", "get_account_commissioning_info", "READ",
                        {"account_number": account_number}, "SUCCESS")
        return _ok(rows[0] if rows else None, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_account_commissioning_info", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_account_commissioning_info", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── D5: get_accounts_by_billing_cycle ────────────────────────────────────────

async def get_accounts_by_billing_cycle(billing_cycle: str,
                                        status: str = "ACTIVE",
                                        limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = [billing_cycle]
    status_clause = ""
    if status and status.upper() != "ALL":
        status_clause = "AND a.STATUS = UPPER(:2)"
        params.append(status)
    params.append(limit)
    lim_pos = len(params)
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                   a.STATUS, a.BILLING_CYCLE, cur.CURRENCY_CODE,
                   c.CUSTOMER_NUMBER
            FROM   MCP_APP.ACCOUNT a
            LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            WHERE  UPPER(a.BILLING_CYCLE) = UPPER(:1)
              {status_clause}
            ORDER BY a.ACCOUNT_NUMBER
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_accounts_by_billing_cycle", "READ",
                        {"billing_cycle": billing_cycle, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_accounts_by_billing_cycle", "READ",
                        {"billing_cycle": billing_cycle}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── D6: get_accounts_pending_termination ──────────────────────────────────────

async def get_accounts_pending_termination(days_ahead: int = 30) -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                   a.STATUS, a.BILLING_CYCLE, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   ad.TERMINATION_DATE,
                   ROUND(ad.TERMINATION_DATE - SYSDATE) AS days_until_termination
            FROM   MCP_APP.ACCOUNT a
            JOIN   MCP_APP.ACCOUNT_DETAILS ad ON ad.ACCOUNT_ID = a.ACCOUNT_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            WHERE  ad.TERMINATION_DATE IS NOT NULL
              AND  ad.TERMINATION_DATE <= SYSDATE + :1
              AND  ad.TERMINATION_DATE >= SYSDATE
            ORDER BY ad.TERMINATION_DATE
        """, [days_ahead])
        await log_audit(_TOOL, "", "get_accounts_pending_termination", "READ",
                        {"days_ahead": days_ahead}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_accounts_pending_termination", "READ",
                        {"days_ahead": days_ahead}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
