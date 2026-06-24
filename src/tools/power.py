"""Group M — Cross-Entity Power Query Tools.

Tools: search_globally, get_customer_health_check, get_inactive_entities,
       get_expiring_products, get_full_hierarchy, get_accounts_no_events
"""
from __future__ import annotations

from typing import Any

import oracledb

from src.db.pool import get_connection
from src.db.resolvers import resolve_customer_number
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "power"
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 500


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _clamp(n: int) -> int:
    return min(max(1, n), _LIMIT_MAX)


def _ok(data: Any, row_count: int | None = None) -> dict:
    r: dict = {"success": True, "data": data}
    if row_count is not None:
        r["row_count"] = row_count
    return r


# ── M1: search_globally ───────────────────────────────────────────────────────

async def search_globally(query: str, limit: int = _LIMIT_DEFAULT) -> dict:
    """Search CUSTOMER_NAME, ACCOUNT_NUMBER, EMAIL, INVOICE_NUMBER in one call."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT entity_type, entity_id, entity_number, name, detail
            FROM (
                SELECT 'CUSTOMER'       AS entity_type,
                       CAST(CUSTOMER_ID AS VARCHAR2(20)) AS entity_id,
                       CUSTOMER_NUMBER  AS entity_number,
                       CUSTOMER_NAME    AS name,
                       STATUS           AS detail
                FROM   MCP_APP.CUSTOMER
                WHERE  UPPER(CUSTOMER_NAME) LIKE UPPER('%' || :1 || '%')
                UNION ALL
                SELECT 'ACCOUNT',
                       CAST(ACCOUNT_ID AS VARCHAR2(20)),
                       ACCOUNT_NUMBER,
                       ACCOUNT_NAME,
                       STATUS
                FROM   MCP_APP.ACCOUNT
                WHERE  UPPER(ACCOUNT_NUMBER) LIKE UPPER('%' || :2 || '%')
                UNION ALL
                SELECT 'CONTACT',
                       CAST(CONTACT_ID AS VARCHAR2(20)),
                       EMAIL,
                       CONTACT_NAME,
                       DESIGNATION
                FROM   MCP_APP.CONTACT
                WHERE  UPPER(EMAIL) LIKE UPPER('%' || :3 || '%')
                UNION ALL
                SELECT 'INVOICE',
                       CAST(BILL_SUMMARY_ID AS VARCHAR2(20)),
                       INVOICE_NUMBER,
                       BILL_STATUS,
                       TO_CHAR(TOTAL_AMOUNT)
                FROM   MCP_APP.BILL_SUMMARY
                WHERE  UPPER(INVOICE_NUMBER) LIKE UPPER('%' || :4 || '%')
            )
            ORDER BY entity_type, entity_number
            FETCH FIRST :5 ROWS ONLY
        """, [query, query, query, query, limit])
        await log_audit(_TOOL, "", "search_globally", "READ",
                        {"query": query}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "search_globally", "READ",
                        {"query": query}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── M2: get_customer_health_check ─────────────────────────────────────────────

async def get_customer_health_check(customer_number: str) -> dict:
    """Run 5 health sub-queries for a customer and return flag summary."""
    conn = await get_connection()
    try:
        cid = await resolve_customer_number(conn, customer_number)
        rows = await _exec(conn, """
            SELECT
                (SELECT COUNT(*) FROM MCP_APP.ADDRESS
                 WHERE CUSTOMER_ID = :1)                          AS address_count,
                (SELECT COUNT(*) FROM MCP_APP.CONTACT
                 WHERE CUSTOMER_ID = :2)                          AS contact_count,
                (SELECT COUNT(*) FROM MCP_APP.CUSTOMER_PRODUCT_DETAILS
                 WHERE CUSTOMER_ID = :3 AND STATUS = 'ACTIVE')    AS active_product_count,
                (SELECT COUNT(*)
                 FROM   MCP_APP.BILL_SUMMARY bs
                 JOIN   MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = bs.ACCOUNT_ID
                 WHERE  a.CUSTOMER_ID = :4
                   AND  bs.BILL_STATUS NOT IN ('PAID', 'CANCELLED'))
                                                                  AS unpaid_bill_count,
                (SELECT COALESCE(SUM(bs2.TOTAL_AMOUNT), 0)
                 FROM   MCP_APP.BILL_SUMMARY bs2
                 JOIN   MCP_APP.ACCOUNT a2 ON a2.ACCOUNT_ID = bs2.ACCOUNT_ID
                 WHERE  a2.CUSTOMER_ID = :5
                   AND  bs2.BILL_STATUS NOT IN ('PAID', 'CANCELLED'))
                                                                  AS unpaid_amount,
                (SELECT COUNT(*)
                 FROM   MCP_APP.COSTED_EVENT ce
                 JOIN   MCP_APP.ACCOUNT a3 ON a3.ACCOUNT_ID = ce.ACCOUNT_ID
                 WHERE  a3.CUSTOMER_ID = :6
                   AND  TRUNC(ce.EVENT_DTM, 'MM') = TRUNC(SYSDATE, 'MM'))
                                                                  AS events_this_month
            FROM DUAL
        """, [cid, cid, cid, cid, cid, cid])

        row = rows[0] if rows else {}
        health = {
            "customer_number": customer_number,
            "missing_address": (row.get("address_count") or 0) == 0,
            "missing_contact": (row.get("contact_count") or 0) == 0,
            "no_active_products": (row.get("active_product_count") or 0) == 0,
            "has_unpaid_bills": (row.get("unpaid_bill_count") or 0) > 0,
            "unpaid_bill_count": row.get("unpaid_bill_count") or 0,
            "unpaid_amount": float(row.get("unpaid_amount") or 0),
            "no_events_this_month": (row.get("events_this_month") or 0) == 0,
            "raw_counts": {
                "addresses": row.get("address_count") or 0,
                "contacts": row.get("contact_count") or 0,
                "active_products": row.get("active_product_count") or 0,
                "events_this_month": row.get("events_this_month") or 0,
            },
        }
        await log_audit(_TOOL, "", "get_customer_health_check", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(health)
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_customer_health_check", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_health_check", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── M3: get_inactive_entities ─────────────────────────────────────────────────

async def get_inactive_entities(entity_type: str | None = None,
                                 limit: int = _LIMIT_DEFAULT) -> dict:
    """Return INACTIVE customers and/or accounts."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        et = (entity_type or "ALL").upper()

        if et == "CUSTOMER":
            rows = await _exec(conn, """
                SELECT 'CUSTOMER'     AS entity_type,
                       CUSTOMER_NUMBER AS entity_number,
                       CUSTOMER_NAME   AS entity_name,
                       STATUS, START_DATE AS relevant_date
                FROM   MCP_APP.CUSTOMER
                WHERE  STATUS = 'INACTIVE'
                ORDER BY CUSTOMER_NUMBER
                FETCH FIRST :1 ROWS ONLY
            """, [limit])
        elif et == "ACCOUNT":
            rows = await _exec(conn, """
                SELECT 'ACCOUNT'     AS entity_type,
                       ACCOUNT_NUMBER AS entity_number,
                       ACCOUNT_NAME   AS entity_name,
                       STATUS, NULL   AS relevant_date
                FROM   MCP_APP.ACCOUNT
                WHERE  STATUS = 'INACTIVE'
                ORDER BY ACCOUNT_NUMBER
                FETCH FIRST :1 ROWS ONLY
            """, [limit])
        else:
            rows = await _exec(conn, """
                SELECT entity_type, entity_number, entity_name,
                       status, relevant_date
                FROM (
                    SELECT 'CUSTOMER'     AS entity_type,
                           CUSTOMER_NUMBER AS entity_number,
                           CUSTOMER_NAME   AS entity_name,
                           STATUS, START_DATE AS relevant_date
                    FROM   MCP_APP.CUSTOMER WHERE STATUS = 'INACTIVE'
                    UNION ALL
                    SELECT 'ACCOUNT', ACCOUNT_NUMBER, ACCOUNT_NAME,
                           STATUS, NULL
                    FROM   MCP_APP.ACCOUNT WHERE STATUS = 'INACTIVE'
                )
                ORDER BY entity_type, entity_number
                FETCH FIRST :1 ROWS ONLY
            """, [limit])

        await log_audit(_TOOL, "", "get_inactive_entities", "READ",
                        {"entity_type": entity_type}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_inactive_entities", "READ",
                        {"entity_type": entity_type}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── M4: get_expiring_products ─────────────────────────────────────────────────

async def get_expiring_products(days_ahead: int = 30) -> dict:
    """Return active products whose END_DATE falls within the next N days."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT cpd.CUST_PRODUCT_ID,
                   cpd.END_DATE,
                   ROUND(cpd.END_DATE - SYSDATE) AS days_until_expiry,
                   p.PRODUCT_CODE, p.PRODUCT_NAME, p.PRODUCT_TYPE,
                   c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   a.ACCOUNT_NUMBER
            FROM   MCP_APP.CUSTOMER_PRODUCT_DETAILS cpd
            JOIN   MCP_APP.PRODUCT p  ON p.PRODUCT_ID  = cpd.PRODUCT_ID
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = cpd.CUSTOMER_ID
            LEFT JOIN MCP_APP.ACCOUNT a ON a.ACCOUNT_ID = cpd.ACCOUNT_ID
            WHERE  cpd.STATUS = 'ACTIVE'
              AND  cpd.END_DATE IS NOT NULL
              AND  cpd.END_DATE BETWEEN SYSDATE AND SYSDATE + :1
            ORDER BY cpd.END_DATE
        """, [days_ahead])
        await log_audit(_TOOL, "", "get_expiring_products", "READ",
                        {"days_ahead": days_ahead}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_expiring_products", "READ",
                        {"days_ahead": days_ahead}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── M5: get_full_hierarchy ────────────────────────────────────────────────────

async def get_full_hierarchy(customer_number: str) -> dict:
    """Return full nested hierarchy: company → customer → accounts → products."""
    conn = await get_connection()
    try:
        # 1. Customer + company
        cust_rows = await _exec(conn, """
            SELECT c.CUSTOMER_ID, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   c.STATUS, c.START_DATE,
                   ic.COMPANY_CODE, ic.COMPANY_NAME,
                   ct.CUSTOMER_TYPE_NAME
            FROM   MCP_APP.CUSTOMER c
            LEFT JOIN MCP_APP.INVOICING_COMPANY ic
                   ON ic.INV_COMPANY_ID = c.INV_COMPANY_ID
            LEFT JOIN MCP_APP.CUSTOMER_TYPE ct
                   ON ct.CUSTOMER_TYPE_ID = c.CUSTOMER_TYPE_ID
            WHERE  UPPER(c.CUSTOMER_NUMBER) = UPPER(:1)
        """, [customer_number])

        if not cust_rows:
            await log_audit(_TOOL, "", "get_full_hierarchy", "READ",
                            {"customer_number": customer_number}, "SUCCESS")
            return _ok(None, 0)

        cust = cust_rows[0]
        cid = cust["customer_id"]

        # 2. Accounts
        acc_rows = await _exec(conn, """
            SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER, a.ACCOUNT_NAME,
                   a.STATUS, a.BILLING_CYCLE, cur.CURRENCY_CODE,
                   ad.BILLABLE_FLAG, ad.COMMISSIONING_DATE, ad.TERMINATION_DATE
            FROM   MCP_APP.ACCOUNT a
            LEFT JOIN MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
            LEFT JOIN MCP_APP.ACCOUNT_DETAILS ad ON ad.ACCOUNT_ID = a.ACCOUNT_ID
            WHERE  a.CUSTOMER_ID = :1
            ORDER BY a.ACCOUNT_NUMBER
        """, [cid])

        # 3. Products (all for this customer, keyed by account_id)
        prod_rows = await _exec(conn, """
            SELECT cpd.ACCOUNT_ID, p.PRODUCT_CODE, p.PRODUCT_NAME,
                   p.PRODUCT_TYPE, cpd.STATUS,
                   cpd.START_DATE, cpd.END_DATE
            FROM   MCP_APP.CUSTOMER_PRODUCT_DETAILS cpd
            JOIN   MCP_APP.PRODUCT p ON p.PRODUCT_ID = cpd.PRODUCT_ID
            WHERE  cpd.CUSTOMER_ID = :1
            ORDER BY cpd.START_DATE DESC
        """, [cid])

        # Build nested structure
        prod_by_acc: dict[int, list] = {}
        for pr in prod_rows:
            aid = pr["account_id"]
            prod_by_acc.setdefault(aid, []).append({
                k: v for k, v in pr.items() if k != "account_id"
            })

        accounts_nested = []
        for acc in acc_rows:
            aid = acc["account_id"]
            accounts_nested.append({
                **acc,
                "products": prod_by_acc.get(aid, []),
            })

        hierarchy = {
            "company": {
                "company_code": cust["company_code"],
                "company_name": cust["company_name"],
            },
            "customer": {
                "customer_number": cust["customer_number"],
                "customer_name": cust["customer_name"],
                "status": cust["status"],
                "start_date": cust["start_date"],
                "customer_type": cust["customer_type_name"],
            },
            "accounts": accounts_nested,
            "account_count": len(accounts_nested),
            "product_count": len(prod_rows),
        }

        await log_audit(_TOOL, "", "get_full_hierarchy", "READ",
                        {"customer_number": customer_number}, "SUCCESS")
        return _ok(hierarchy)
    except ValueError as exc:
        await log_audit(_TOOL, "", "get_full_hierarchy", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return {"success": False, "error_code": "NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        await log_audit(_TOOL, "", "get_full_hierarchy", "READ",
                        {"customer_number": customer_number},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── M6: get_accounts_no_events ────────────────────────────────────────────────

async def get_accounts_no_events(limit: int = _LIMIT_DEFAULT) -> dict:
    """Return active accounts with no costed events in the current calendar month."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT a.ACCOUNT_NUMBER, a.ACCOUNT_NAME, a.STATUS,
                   a.BILLING_CYCLE, c.CUSTOMER_NUMBER, c.CUSTOMER_NAME,
                   ad.COMMISSIONING_DATE
            FROM   MCP_APP.ACCOUNT a
            JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID
            LEFT JOIN MCP_APP.ACCOUNT_DETAILS ad ON ad.ACCOUNT_ID = a.ACCOUNT_ID
            LEFT JOIN (
                SELECT DISTINCT ACCOUNT_ID
                FROM   MCP_APP.COSTED_EVENT
                WHERE  TRUNC(EVENT_DTM, 'MM') = TRUNC(SYSDATE, 'MM')
            ) ce ON ce.ACCOUNT_ID = a.ACCOUNT_ID
            WHERE  a.STATUS = 'ACTIVE'
              AND  ce.ACCOUNT_ID IS NULL
            ORDER BY a.ACCOUNT_NUMBER
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        await log_audit(_TOOL, "", "get_accounts_no_events", "READ",
                        {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_accounts_no_events", "READ",
                        {}, "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()
