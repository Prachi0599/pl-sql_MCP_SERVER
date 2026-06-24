"""Groups E & F (read side) — Product & Billing Read Tools.

Group E: get_products, get_product_by_code, get_customer_products
Group F: get_bills_by_account, get_bill_by_invoice_number,
         get_billing_summary_by_customer, get_unpaid_bills,
         get_monthly_revenue, get_revenue_by_product_type,
         get_pending_adjustments
"""
from __future__ import annotations

from typing import Any

import oracledb

from src.db.pool import get_connection
from src.db.resolvers import resolve_account_number, resolve_customer_number
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "billing"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


async def _callfunc_cursor(conn: oracledb.AsyncConnection,
                           func_name: str,
                           args: list) -> list[dict]:
    """Call an Oracle FUNCTION that returns a REF CURSOR."""
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


# ── E1: get_products ──────────────────────────────────────────────────────────

async def get_products(product_type: str | None = None,
                       status: str = "ACTIVE") -> dict:
    params: list = []
    clauses = []
    p = 1
    if status and status.upper() != "ALL":
        clauses.append(f"STATUS = UPPER(:{p})")
        params.append(status)
        p += 1
    if product_type:
        clauses.append(f"UPPER(PRODUCT_TYPE) = UPPER(:{p})")
        params.append(product_type)
        p += 1
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_TYPE, STATUS
        FROM   MCP_APP.PRODUCT
        {where}
        ORDER BY PRODUCT_CODE
    """
    conn = await get_connection()
    try:
        rows = await _exec(conn, sql, params)
        await log_audit(_TOOL, "", "get_products", "READ",
                        {"product_type": product_type, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_products", "READ",
                        {"product_type": product_type}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── E2: get_product_by_code ───────────────────────────────────────────────────

async def get_product_by_code(product_code: str) -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_TYPE, STATUS
            FROM   MCP_APP.PRODUCT
            WHERE  UPPER(PRODUCT_CODE) = UPPER(:1)
        """, [product_code])
        await log_audit(_TOOL, "", "get_product_by_code", "READ",
                        {"product_code": product_code}, "SUCCESS")
        return _ok(rows[0] if rows else None, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_product_by_code", "READ",
                        {"product_code": product_code}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── E3: get_customer_products ─────────────────────────────────────────────────

async def get_customer_products(customer_number: str,
                                status: str | None = None) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        params: list = [cid]
        status_clause = ""
        if status:
            status_clause = "AND cpd.STATUS = UPPER(:2)"
            params.append(status)
        rows = await _exec(conn, f"""
            SELECT p.PRODUCT_CODE, p.PRODUCT_NAME, p.PRODUCT_TYPE,
                   cpd.STATUS, cpd.START_DATE, cpd.END_DATE,
                   a.ACCOUNT_NUMBER
            FROM   MCP_APP.CUSTOMER_PRODUCT_DETAILS cpd
            JOIN   MCP_APP.PRODUCT p ON p.PRODUCT_ID = cpd.PRODUCT_ID
            LEFT JOIN MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = cpd.ACCOUNT_ID
            WHERE  cpd.CUSTOMER_ID = :1
            {status_clause}
            ORDER BY cpd.START_DATE DESC
        """, params)
        await log_audit(_TOOL, "", "get_customer_products", "READ",
                        {"customer_number": customer_number, "status": status},
                        "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_customer_products", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_products", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F1: get_bills_by_account ──────────────────────────────────────────────────

async def get_bills_by_account(account_number: str,
                                date_from: str | None = None,
                                date_to: str | None = None,
                                status: str | None = None) -> dict:
    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        # Try package function first (returns all bills for account)
        try:
            rows = await _callfunc_cursor(
                conn, "BILLING_PKG.GET_BILL_DETAILS", [account_id])
        except Exception:
            # Fallback to direct SQL
            rows = await _exec(conn, """
                SELECT bs.BILL_SUMMARY_ID, bs.INVOICE_NUMBER, bs.BILLING_MONTH,
                       bs.BILL_AMOUNT, bs.TAX_AMOUNT, bs.TOTAL_AMOUNT,
                       bs.BILL_STATUS, cur.CURRENCY_CODE
                FROM   MCP_APP.BILL_SUMMARY bs
                LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = bs.CURRENCY_ID
                WHERE  bs.ACCOUNT_ID = :1
                ORDER BY bs.BILLING_MONTH DESC
            """, [account_id])

        # Client-side date and status filters
        if date_from:
            rows = [r for r in rows
                    if r.get("billing_month") and str(r["billing_month"]) >= date_from]
        if date_to:
            rows = [r for r in rows
                    if r.get("billing_month") and str(r["billing_month"]) <= date_to]
        if status:
            rows = [r for r in rows
                    if str(r.get("bill_status", "")).upper() == status.upper()]

        await log_audit(_TOOL, "BILLING_PKG", "GET_BILL_DETAILS", "READ",
                        {"account_number": account_number}, "SUCCESS")
        return _ok(rows, len(rows))
    except ValueError as exc:
        await log_audit(_TOOL, "BILLING_PKG", "GET_BILL_DETAILS", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "BILLING_PKG", "GET_BILL_DETAILS", "READ",
                        {"account_number": account_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F2: get_bill_by_invoice_number ────────────────────────────────────────────

async def get_bill_by_invoice_number(invoice_number: str) -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT bs.BILL_SUMMARY_ID, bs.INVOICE_NUMBER, bs.BILLING_MONTH,
                   bs.BILL_AMOUNT, bs.TAX_AMOUNT, bs.TOTAL_AMOUNT,
                   bs.BILL_STATUS, cur.CURRENCY_CODE,
                   a.ACCOUNT_NUMBER, c.CUSTOMER_NUMBER
            FROM   MCP_APP.BILL_SUMMARY bs
            LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = bs.CURRENCY_ID
            JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = bs.ACCOUNT_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            WHERE  UPPER(bs.INVOICE_NUMBER) = UPPER(:1)
        """, [invoice_number])
        await log_audit(_TOOL, "", "get_bill_by_invoice_number", "READ",
                        {"invoice_number": invoice_number}, "SUCCESS")
        return _ok(rows[0] if rows else None, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_bill_by_invoice_number", "READ",
                        {"invoice_number": invoice_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F3: get_billing_summary_by_customer ───────────────────────────────────────

async def get_billing_summary_by_customer(customer_number: str) -> dict:
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        rows = await _exec(conn, """
            SELECT c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   COUNT(bs.BILL_SUMMARY_ID)                      AS invoice_count,
                   SUM(bs.TOTAL_AMOUNT)                           AS total_billed,
                   SUM(CASE WHEN bs.BILL_STATUS NOT IN ('PAID','CANCELLED')
                            THEN bs.TOTAL_AMOUNT ELSE 0 END)      AS outstanding_amount,
                   SUM(CASE WHEN bs.BILL_STATUS = 'PAID'
                            THEN bs.TOTAL_AMOUNT ELSE 0 END)      AS paid_amount
            FROM   MCP_APP.BILL_SUMMARY bs
            JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = bs.ACCOUNT_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            WHERE  c.CUSTOMER_ID = :1
            GROUP BY c.CUSTOMER_NUMBER, c.CUSTOMER_NAME
        """, [cid])
        await log_audit(_TOOL, "", "get_billing_summary_by_customer", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(rows[0] if rows else None, 1 if rows else 0)
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_billing_summary_by_customer", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_billing_summary_by_customer", "READ",
                        {"customer_number": customer_number}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F4: get_unpaid_bills ──────────────────────────────────────────────────────

async def get_unpaid_bills(currency_code: str | None = None,
                           limit: int = _LIMIT_DEFAULT) -> dict:
    limit = _clamp(limit)
    params: list = []
    currency_clause = ""
    p = 1
    if currency_code:
        currency_clause = f"AND UPPER(cur.CURRENCY_CODE) = UPPER(:{p})"
        params.append(currency_code)
        p += 1
    params.append(limit)
    lim_pos = p
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT bs.BILL_SUMMARY_ID, bs.INVOICE_NUMBER, bs.BILLING_MONTH,
                   bs.TOTAL_AMOUNT, bs.BILL_STATUS,
                   cur.CURRENCY_CODE, a.ACCOUNT_NUMBER, c.CUSTOMER_NUMBER
            FROM   MCP_APP.BILL_SUMMARY bs
            JOIN   MCP_APP.ACCOUNT a  ON a.ACCOUNT_ID   = bs.ACCOUNT_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID  = a.CUSTOMER_ID
            LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = bs.CURRENCY_ID
            WHERE  bs.BILL_STATUS NOT IN ('PAID', 'CANCELLED')
            {currency_clause}
            ORDER BY bs.BILLING_MONTH DESC
            FETCH FIRST :{lim_pos} ROWS ONLY
        """, params)
        await log_audit(_TOOL, "", "get_unpaid_bills", "READ",
                        {"currency_code": currency_code}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_unpaid_bills", "READ",
                        {"currency_code": currency_code}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F5: get_monthly_revenue ───────────────────────────────────────────────────

async def get_monthly_revenue(months: int = 12) -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT TO_CHAR(BILLING_MONTH, 'YYYY-MM') AS month,
                   SUM(TOTAL_AMOUNT)                 AS total_revenue,
                   COUNT(*)                          AS invoice_count
            FROM   MCP_APP.BILL_SUMMARY
            WHERE  BILL_STATUS != 'CANCELLED'
            GROUP BY TO_CHAR(BILLING_MONTH, 'YYYY-MM')
            ORDER BY month DESC
            FETCH FIRST :1 ROWS ONLY
        """, [months])
        await log_audit(_TOOL, "", "get_monthly_revenue", "READ",
                        {"months": months}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_monthly_revenue", "READ",
                        {"months": months}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F6: get_revenue_by_product_type ──────────────────────────────────────────

async def get_revenue_by_product_type() -> dict:
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT p.PRODUCT_TYPE,
                   SUM(bs.TOTAL_AMOUNT)           AS total_revenue,
                   COUNT(DISTINCT bs.ACCOUNT_ID)  AS account_count,
                   COUNT(bs.BILL_SUMMARY_ID)       AS invoice_count
            FROM   MCP_APP.BILL_SUMMARY bs
            JOIN   MCP_APP.CUSTOMER_PRODUCT_DETAILS cpd
                   ON cpd.ACCOUNT_ID = bs.ACCOUNT_ID
            JOIN   MCP_APP.PRODUCT p ON p.PRODUCT_ID = cpd.PRODUCT_ID
            WHERE  bs.BILL_STATUS != 'CANCELLED'
            GROUP BY p.PRODUCT_TYPE
            ORDER BY total_revenue DESC
        """)
        await log_audit(_TOOL, "", "get_revenue_by_product_type", "READ",
                        {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_revenue_by_product_type", "READ",
                        {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── F7: get_pending_adjustments ───────────────────────────────────────────────

async def get_pending_adjustments() -> dict:
    conn = await get_connection()
    try:
        # Package function — no args, returns REF CURSOR
        try:
            rows = await _callfunc_cursor(
                conn, "BILLING_ADJUSTMENT_PKG.GET_PENDING_ADJUSTMENTS", [])
        except Exception:
            rows = await _exec(conn, """
                SELECT ba.ADJUSTMENT_ID, ba.ADJUSTMENT_TYPE, ba.ADJUSTMENT_AMOUNT,
                       ba.REASON, ba.STATUS, ba.REQUESTED_BY,
                       bs.INVOICE_NUMBER, a.ACCOUNT_NUMBER
                FROM   MCP_APP.BILLING_ADJUSTMENT ba
                JOIN   MCP_APP.BILL_SUMMARY bs ON bs.BILL_SUMMARY_ID = ba.BILL_SUMMARY_ID
                JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = ba.ACCOUNT_ID
                WHERE  ba.STATUS = 'PENDING'
                ORDER BY ba.CREATED_DTM DESC
            """)
        await log_audit(_TOOL, "BILLING_ADJUSTMENT_PKG",
                        "GET_PENDING_ADJUSTMENTS", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "BILLING_ADJUSTMENT_PKG",
                        "GET_PENDING_ADJUSTMENTS", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
