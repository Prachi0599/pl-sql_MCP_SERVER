"""Group B (read side) — Customer Read Tools.

Covers: search_customers, get_customer_by_number, get_customer_360,
        get_customers_by_company, get_customer_summary_stats.
"""
from __future__ import annotations

import asyncio
from typing import Any

from src.db.pool import get_connection
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "customer"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500
_QUERY_TIMEOUT: float = 30.0  # seconds; patched in tests


async def _exec(conn, sql: str, params: list | None = None) -> list[dict]:
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


# ── search_customers ──────────────────────────────────────────────────────────

async def search_customers(
    name: str | None = None,
    status: str | None = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> dict:
    limit = _clamp(limit)
    conditions = ["1=1"]
    params: list = []
    p = 1  # positional bind counter
    if name:
        conditions.append(f"UPPER(c.CUSTOMER_NAME) LIKE UPPER('%' || :{p} || '%')")
        params.append(name)
        p += 1
    if status:
        conditions.append(f"c.STATUS = UPPER(:{p})")
        params.append(status)
        p += 1
    params += [offset, limit]
    where = " AND ".join(conditions)
    sql = f"""
        SELECT c.CUSTOMER_ID, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
               c.STATUS, ct.CUSTOMER_TYPE_NAME, ic.COMPANY_CODE,
               c.START_DATE
        FROM   MCP_APP.CUSTOMER c
        LEFT JOIN MCP_APP.CUSTOMER_TYPE ct
               ON ct.CUSTOMER_TYPE_ID = c.CUSTOMER_TYPE_ID
        LEFT JOIN MCP_APP.INVOICING_COMPANY ic
               ON ic.INV_COMPANY_ID = c.INV_COMPANY_ID
        WHERE  {where}
        ORDER BY c.CUSTOMER_NUMBER
        OFFSET :{p} ROWS FETCH NEXT :{p+1} ROWS ONLY
    """
    conn = await get_connection()
    try:
        rows = await asyncio.wait_for(_exec(conn, sql, params), timeout=_QUERY_TIMEOUT)
        await log_audit(_TOOL, "", "search_customers", "READ",
                        {"name": name, "status": status, "limit": limit, "offset": offset},
                        "SUCCESS")
        return _ok(rows, len(rows))
    except asyncio.TimeoutError:
        await log_audit(_TOOL, "", "search_customers", "READ",
                        {"name": name, "status": status}, "ERROR", "Query timed out")
        return {
            "success": False,
            "error_code": "TIMEOUT",
            "message": f"Query timed out after {_QUERY_TIMEOUT}s",
        }
    except Exception as exc:
        await log_audit(_TOOL, "", "search_customers", "READ",
                        {"name": name, "status": status}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── get_customer_by_number ────────────────────────────────────────────────────

async def get_customer_by_number(customer_number: str) -> dict:
    sql = """
        SELECT c.CUSTOMER_ID, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
               c.STATUS, ct.CUSTOMER_TYPE_NAME, ic.COMPANY_CODE,
               ic.COMPANY_NAME, c.START_DATE
        FROM   MCP_APP.CUSTOMER c
        LEFT JOIN MCP_APP.CUSTOMER_TYPE ct
               ON ct.CUSTOMER_TYPE_ID = c.CUSTOMER_TYPE_ID
        LEFT JOIN MCP_APP.INVOICING_COMPANY ic
               ON ic.INV_COMPANY_ID = c.INV_COMPANY_ID
        WHERE  UPPER(c.CUSTOMER_NUMBER) = UPPER(:1)
    """
    conn = await get_connection()
    try:
        rows = await _exec(conn, sql, [customer_number])
        if not rows:
            await log_audit(_TOOL, "", "get_customer_by_number", "READ",
                            {"customer_number": customer_number}, "SUCCESS")
            return _ok(None, 0)
        await log_audit(_TOOL, "", "get_customer_by_number", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(rows[0], 1)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_by_number", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── get_customer_360 ──────────────────────────────────────────────────────────

async def get_customer_360(customer_number: str) -> dict:
    conn = await get_connection()
    try:
        # 1. Customer profile
        cust_rows = await _exec(conn, """
            SELECT c.CUSTOMER_ID, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   c.STATUS, ct.CUSTOMER_TYPE_NAME, ic.COMPANY_CODE
            FROM   MCP_APP.CUSTOMER c
            LEFT JOIN MCP_APP.CUSTOMER_TYPE ct ON ct.CUSTOMER_TYPE_ID = c.CUSTOMER_TYPE_ID
            LEFT JOIN MCP_APP.INVOICING_COMPANY ic ON ic.INV_COMPANY_ID = c.INV_COMPANY_ID
            WHERE  UPPER(c.CUSTOMER_NUMBER) = UPPER(:1)
        """, [customer_number])

        if not cust_rows:
            await log_audit(_TOOL, "", "get_customer_360", "READ",
                            {"customer_number": customer_number}, "SUCCESS")
            return _ok(None, 0)

        cust = cust_rows[0]
        cid = cust["customer_id"]

        # 2. Addresses
        addresses = await _exec(conn, """
            SELECT ADDRESS_ID, ADDRESS_TYPE, ADDRESS_LINE1, CITY, COUNTRY
            FROM   MCP_APP.ADDRESS WHERE CUSTOMER_ID = :1
        """, [cid])

        # 3. Contacts
        contacts = await _exec(conn, """
            SELECT con.CONTACT_ID, con.CONTACT_NAME, con.DESIGNATION, con.EMAIL,
                   cd.PHONE_NUMBER
            FROM   MCP_APP.CONTACT con
            LEFT JOIN MCP_APP.CONTACT_DETAILS cd ON cd.CONTACT_ID = con.CONTACT_ID
            WHERE  con.CUSTOMER_ID = :1
        """, [cid])

        # 4. Accounts
        accounts = await _exec(conn, """
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.STATUS,
                   a.BILLING_CYCLE, cur.CURRENCY_CODE
            FROM   MCP_APP.ACCOUNT a
            LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
            WHERE  a.CUSTOMER_ID = :1
        """, [cid])

        # 5. Products
        products = await _exec(conn, """
            SELECT p.PRODUCT_CODE, p.PRODUCT_NAME, p.PRODUCT_TYPE,
                   cpd.STATUS, cpd.START_DATE, cpd.END_DATE
            FROM   MCP_APP.CUSTOMER_PRODUCT_DETAILS cpd
            JOIN   MCP_APP.PRODUCT p ON p.PRODUCT_ID = cpd.PRODUCT_ID
            WHERE  cpd.CUSTOMER_ID = :1
        """, [cid])

        # 6. Latest bill
        bills = await _exec(conn, """
            SELECT bs.INVOICE_NUMBER, bs.BILL_AMOUNT, bs.TOTAL_AMOUNT,
                   bs.BILL_STATUS, bs.BILLING_MONTH
            FROM   MCP_APP.BILL_SUMMARY bs
            JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = bs.ACCOUNT_ID
            WHERE  a.CUSTOMER_ID = :1
            ORDER BY bs.BILLING_MONTH DESC, bs.BILL_SUMMARY_ID DESC
            FETCH FIRST 1 ROWS ONLY
        """, [cid])

        data = {
            "customer": cust,
            "addresses": addresses,
            "contacts": contacts,
            "accounts": accounts,
            "products": products,
            "latest_bill": bills[0] if bills else None,
        }
        await log_audit(_TOOL, "", "get_customer_360", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(data, 1)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_360", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── get_customers_by_company ──────────────────────────────────────────────────

async def get_customers_by_company(company_code: str,
                                   status: str = "ACTIVE",
                                   limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = [company_code]
    status_clause = ""
    if status and status.upper() != "ALL":
        status_clause = "AND c.STATUS = UPPER(:2)"
        params.append(status)
    params.append(limit)
    lim_pos = len(params)
    sql = f"""
        SELECT c.CUSTOMER_ID, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME, c.STATUS
        FROM   MCP_APP.CUSTOMER c
        JOIN   MCP_APP.INVOICING_COMPANY ic ON ic.INV_COMPANY_ID = c.INV_COMPANY_ID
        WHERE  UPPER(ic.COMPANY_CODE) = UPPER(:1)
          {status_clause}
        ORDER BY c.CUSTOMER_NUMBER
        FETCH FIRST :{lim_pos} ROWS ONLY
    """
    conn = await get_connection()
    try:
        rows = await _exec(conn, sql, params)
        await log_audit(_TOOL, "", "get_customers_by_company", "READ",
                        {"company_code": company_code, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customers_by_company", "READ",
                        {"company_code": company_code}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── get_customer_summary_stats ────────────────────────────────────────────────

async def get_customer_summary_stats() -> dict:
    conn = await get_connection()
    try:
        totals = await _exec(conn, """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN STATUS = 'ACTIVE'   THEN 1 ELSE 0 END) AS active,
                   SUM(CASE WHEN STATUS = 'INACTIVE' THEN 1 ELSE 0 END) AS inactive
            FROM   MCP_APP.CUSTOMER
        """)
        by_type = await _exec(conn, """
            SELECT ct.CUSTOMER_TYPE_NAME, COUNT(*) AS count
            FROM   MCP_APP.CUSTOMER c
            JOIN   MCP_APP.CUSTOMER_TYPE ct ON ct.CUSTOMER_TYPE_ID = c.CUSTOMER_TYPE_ID
            GROUP BY ct.CUSTOMER_TYPE_NAME
            ORDER BY count DESC
        """)
        data = {**totals[0], "by_type": by_type}
        await log_audit(_TOOL, "", "get_customer_summary_stats", "READ", {}, "SUCCESS")
        return _ok(data)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_summary_stats", "READ",
                        {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
