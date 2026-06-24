"""Groups A & J — Reference & Lookup Read Tools.

Covers: get_providers, get_provider_details, get_invoicing_companies,
        get_currencies, get_currency_by_code, get_customer_types.
"""
from __future__ import annotations

from typing import Any

from src.db.pool import get_connection
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "reference"


async def _exec(sql: str, params: list | None = None) -> list[dict]:
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


# ── get_providers ─────────────────────────────────────────────────────────────

async def get_providers(status: str = "ACTIVE") -> dict:
    if status.upper() == "ALL":
        sql = """
            SELECT PROVIDER_ID, PROVIDER_CODE, PROVIDER_NAME,
                   SERVICE_TYPE, COUNTRY, STATUS
            FROM   MCP_APP.PROVIDER
            ORDER BY PROVIDER_CODE
        """
        params: list = []
    else:
        sql = """
            SELECT PROVIDER_ID, PROVIDER_CODE, PROVIDER_NAME,
                   SERVICE_TYPE, COUNTRY, STATUS
            FROM   MCP_APP.PROVIDER
            WHERE  STATUS = UPPER(:1)
            ORDER BY PROVIDER_CODE
        """
        params = [status]
    try:
        rows = await _exec(sql, params)
        await log_audit(_TOOL, "", "get_providers", "READ",
                        {"status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_providers", "READ",
                        {"status": status}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── get_provider_details ──────────────────────────────────────────────────────

async def get_provider_details(provider_code: str) -> dict:
    sql = """
        SELECT PROVIDER_ID, PROVIDER_CODE, PROVIDER_NAME,
               SERVICE_TYPE, COUNTRY, STATUS, CREATED_DATE
        FROM   MCP_APP.PROVIDER
        WHERE  UPPER(PROVIDER_CODE) = UPPER(:1)
    """
    try:
        rows = await _exec(sql, [provider_code])
        if not rows:
            await log_audit(_TOOL, "", "get_provider_details", "READ",
                            {"provider_code": provider_code}, "SUCCESS")
            return _ok(None, 0)
        await log_audit(_TOOL, "", "get_provider_details", "READ",
                        {"provider_code": provider_code}, "SUCCESS")
        return _ok(rows[0], 1)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_provider_details", "READ",
                        {"provider_code": provider_code}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── get_invoicing_companies ───────────────────────────────────────────────────

async def get_invoicing_companies(country: str | None = None,
                                  status: str = "ACTIVE") -> dict:
    if country:
        sql = """
            SELECT INV_COMPANY_ID, COMPANY_CODE, COMPANY_NAME,
                   COUNTRY, STATUS
            FROM   MCP_APP.INVOICING_COMPANY
            WHERE  UPPER(COUNTRY) = UPPER(:1)
              AND  STATUS         = UPPER(:2)
            ORDER BY COMPANY_CODE
        """
        params: list = [country, status]
    else:
        if status.upper() == "ALL":
            sql = """
                SELECT INV_COMPANY_ID, COMPANY_CODE, COMPANY_NAME,
                       COUNTRY, STATUS
                FROM   MCP_APP.INVOICING_COMPANY
                ORDER BY COMPANY_CODE
            """
            params = []
        else:
            sql = """
                SELECT INV_COMPANY_ID, COMPANY_CODE, COMPANY_NAME,
                       COUNTRY, STATUS
                FROM   MCP_APP.INVOICING_COMPANY
                WHERE  STATUS = UPPER(:1)
                ORDER BY COMPANY_CODE
            """
            params = [status]
    try:
        rows = await _exec(sql, params)
        await log_audit(_TOOL, "", "get_invoicing_companies", "READ",
                        {"country": country, "status": status}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_invoicing_companies", "READ",
                        {"country": country, "status": status}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── get_currencies ────────────────────────────────────────────────────────────

async def get_currencies() -> dict:
    sql = """
        SELECT CURRENCY_ID, CURRENCY_CODE, CURRENCY_NAME
        FROM   MCP_APP.CURRENCY
        ORDER BY CURRENCY_CODE
    """
    try:
        rows = await _exec(sql)
        await log_audit(_TOOL, "", "get_currencies", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_currencies", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── get_currency_by_code ──────────────────────────────────────────────────────

async def get_currency_by_code(currency_code: str) -> dict:
    sql = """
        SELECT CURRENCY_ID, CURRENCY_CODE, CURRENCY_NAME
        FROM   MCP_APP.CURRENCY
        WHERE  UPPER(CURRENCY_CODE) = UPPER(:1)
    """
    try:
        rows = await _exec(sql, [currency_code])
        if not rows:
            await log_audit(_TOOL, "", "get_currency_by_code", "READ",
                            {"currency_code": currency_code}, "SUCCESS")
            return _ok(None, 0)
        await log_audit(_TOOL, "", "get_currency_by_code", "READ",
                        {"currency_code": currency_code}, "SUCCESS")
        return _ok(rows[0], 1)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_currency_by_code", "READ",
                        {"currency_code": currency_code}, "ERROR", str(exc))
        return map_oracle_error(exc)


# ── get_customer_types ────────────────────────────────────────────────────────

async def get_customer_types() -> dict:
    sql = """
        SELECT CUSTOMER_TYPE_ID, CUSTOMER_TYPE_CODE, CUSTOMER_TYPE_NAME
        FROM   MCP_APP.CUSTOMER_TYPE
        ORDER BY CUSTOMER_TYPE_CODE
    """
    try:
        rows = await _exec(sql)
        await log_audit(_TOOL, "", "get_customer_types", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_customer_types", "READ", {}, "ERROR", str(exc))
        return map_oracle_error(exc)
