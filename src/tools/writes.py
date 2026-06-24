"""All write tools — Groups A, B, C, D, E, F, G, I, J.

Every write tool:
  1. Validates inputs — returns VALIDATION_ERROR before touching DB.
  2. Resolves code references to IDs.
  3. Calls create_approval_request(conn, ...) — stores the DML as NEW_VALUE JSON.
  4. Returns {success:True, request_id:N, status:'PENDING', ...}.

Actual DML executes only when approve_request(request_id, approved_by) is called.

NEW_VALUE JSON formats:
  Package proc:  {"params": [arg1, ...]}
  Direct SQL:    {"sql": "INSERT ...", "params": [...]}   package_name="DIRECT_SQL"
  Multi-SQL:     {"statements": [{"sql":..,"params":..}]}  package_name="DIRECT_SQL"
  + post_query:  {"post_query": {"sql": ..., "params": [...]}}  — any format
"""
from __future__ import annotations

import json
from typing import Any

import oracledb

from src.db.pool import get_connection
from src.db.resolvers import (
    resolve_account_number,
    resolve_company_code,
    resolve_currency_code,
    resolve_customer_number,
    resolve_customer_type_code,
    resolve_product_code,
    resolve_provider_code,
)
from src.tools.approval import create_approval_request
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "writes"


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _ok(data: Any) -> dict:
    return {"success": True, **data}


def _validation_error(message: str) -> dict:
    return {"success": False, "error_code": "VALIDATION_ERROR", "message": message}


def _not_found(message: str) -> dict:
    return {"success": False, "error_code": "NOT_FOUND", "message": str(message)}


def _no_change_msg(message: str, **extra: Any) -> dict:
    """Returned by any write tool when the requested change is already satisfied
    (a no-op / duplicate) — no approval request is created."""
    return {"success": True, "no_change": True, "status": "NO_CHANGE",
            "message": message, **extra}


def _no_change(label: str, current: Any) -> dict:
    """Convenience for UPDATE tools: the target value already equals the current."""
    return _no_change_msg(
        f"{label} is already '{current}' - no change needed.",
        current_value=current, requested_value=current,
    )


async def _current_value(conn: oracledb.AsyncConnection, sql: str, params: list):
    """Best-effort read of one scalar (the current value of a column).

    Returns None if the row or column is unavailable, so callers simply proceed
    to stage the change as normal (no false no-op detection)."""
    try:
        rows = await _exec(conn, sql, params)
    except Exception:
        return None
    if not rows:
        return None
    return next(iter(rows[0].values()), None)


# ── Group A: Provider ─────────────────────────────────────────────────────────

async def create_provider(
    provider_code: str,
    provider_name: str,
    service_type: str,
    country: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Create a new provider (DIRECT_SQL INSERT into PROVIDER)."""
    if not provider_code or not provider_code.strip():
        return _validation_error("provider_code is required")
    if not provider_name or not provider_name.strip():
        return _validation_error("provider_name is required")

    conn = await get_connection()
    try:
        existing = await _current_value(
            conn,
            "SELECT PROVIDER_CODE FROM MCP_APP.PROVIDER WHERE UPPER(PROVIDER_CODE) = UPPER(:1)",
            [provider_code])
        if existing is not None:
            return _no_change_msg(
                f"Provider '{provider_code.upper()}' already exists - no change needed.",
                current_value=existing)

        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.PROVIDER "
                "(PROVIDER_ID, PROVIDER_CODE, PROVIDER_NAME, SERVICE_TYPE, STATUS, CREATED_DATE) "
                "VALUES (SEQ_PROVIDER.NEXTVAL, :1, :2, :3, 'ACTIVE', SYSDATE)"
            ),
            "params": [provider_code.upper(), provider_name, service_type or ""],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_PROVIDER",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "PROVIDER", "create_provider", "INSERT",
                        {"provider_code": provider_code}, "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_provider_status(
    provider_code: str,
    new_status: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update PROVIDER.STATUS via direct SQL after approval."""
    if not new_status or not new_status.strip():
        return _validation_error("new_status is required")

    conn = await get_connection()
    try:
        provider_id = await resolve_provider_code(conn, provider_code)
        target = new_status.upper()
        current = await _current_value(
            conn, "SELECT STATUS FROM MCP_APP.PROVIDER WHERE PROVIDER_ID = :1",
            [provider_id])
        if current is not None and str(current).upper() == target:
            return _no_change(f"Provider {provider_code} status", current)

        new_val = json.dumps({
            "sql": "UPDATE MCP_APP.PROVIDER SET STATUS = :2 WHERE PROVIDER_ID = :1",
            "params": [provider_id, target],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="UPDATE_PROVIDER_STATUS",
            action_type="UPDATE",
            old_value=json.dumps({"provider_code": provider_code, "old_status": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "PROVIDER", "update_provider_status", "UPDATE",
                        {"provider_code": provider_code, "new_status": new_status},
                        "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": target})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group B: Customer ─────────────────────────────────────────────────────────

async def create_customer(
    customer_name: str,
    company_code: str,
    customer_type_code: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Create a new customer via CUSTOMER_PKG.CREATE_CUSTOMER after approval."""
    if not customer_name or not customer_name.strip():
        return _validation_error("customer_name is required")

    conn = await get_connection()
    try:
        company_id = await resolve_company_code(conn, company_code)
        type_id = await resolve_customer_type_code(conn, customer_type_code)

        seq_rows = await _exec(
            conn,
            "SELECT 'CUST-' || LPAD(SEQ_CUSTOMER.NEXTVAL, 6, '0') AS customer_number FROM DUAL"
        )
        customer_number = seq_rows[0]["customer_number"]

        new_val = json.dumps({
            "params": [company_id, type_id, customer_name, customer_number]
        })
        req = await create_approval_request(
            conn,
            package_name="CUSTOMER_PKG",
            procedure_name="CREATE_CUSTOMER",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CUSTOMER_PKG", "create_customer", "INSERT",
                        {"customer_name": customer_name, "customer_number": customer_number},
                        "SUCCESS")
        return _ok({**req, "customer_number": customer_number})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_customer_status(
    customer_number: str,
    new_status: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update CUSTOMER.STATUS via CUSTOMER_PKG.UPDATE_CUSTOMER_STATUS after approval."""
    if not new_status or not new_status.strip():
        return _validation_error("new_status is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        target = new_status.upper()
        current = await _current_value(
            conn, "SELECT STATUS FROM MCP_APP.CUSTOMER WHERE CUSTOMER_ID = :1",
            [customer_id])
        if current is not None and str(current).upper() == target:
            return _no_change(f"Customer {customer_number} status", current)

        new_val = json.dumps({"params": [customer_id, target]})
        req = await create_approval_request(
            conn,
            package_name="CUSTOMER_PKG",
            procedure_name="UPDATE_CUSTOMER_STATUS",
            action_type="UPDATE",
            old_value=json.dumps({"customer_number": customer_number, "old_status": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CUSTOMER_PKG", "update_customer_status", "UPDATE",
                        {"customer_number": customer_number, "new_status": new_status},
                        "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": target})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group C: Address & Contact ────────────────────────────────────────────────

async def add_customer_address(
    customer_number: str,
    address_type: str,
    address_line1: str,
    city: str,
    country: str,
    state: str = "",
    postal_code: str = "",
    requested_by: str = "mcp_user",
) -> dict:
    """Insert an ADDRESS row for a customer after approval."""
    if not city or not city.strip():
        return _validation_error("city is required")
    if not address_line1 or not address_line1.strip():
        return _validation_error("address_line1 is required")
    if not country or not country.strip():
        return _validation_error("country is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.ADDRESS "
                "(ADDRESS_ID, CUSTOMER_ID, ADDRESS_TYPE, ADDRESS_LINE1, CITY, STATE, COUNTRY, POSTAL_CODE) "
                "VALUES (SEQ_ADDRESS.NEXTVAL, :1, :2, :3, :4, :5, :6, :7)"
            ),
            "params": [
                customer_id, address_type or "BILLING",
                address_line1, city, state or None, country, postal_code or None,
            ],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_ADDRESS",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "ADDRESS", "add_customer_address", "INSERT",
                        {"customer_number": customer_number, "city": city}, "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def add_customer_contact(
    customer_number: str,
    contact_name: str,
    designation: str,
    email: str,
    phone_number: str = "",
    alternate_email: str = "",
    requested_by: str = "mcp_user",
) -> dict:
    """Insert CONTACT + CONTACT_DETAILS rows in a single PL/SQL block after approval."""
    if not email or not email.strip():
        return _validation_error("email is required")
    if not contact_name or not contact_name.strip():
        return _validation_error("contact_name is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        new_val = json.dumps({
            "sql": (
                "DECLARE v_cid NUMBER; "
                "BEGIN "
                "  SELECT SEQ_CONTACT.NEXTVAL INTO v_cid FROM DUAL; "
                "  INSERT INTO MCP_APP.CONTACT "
                "    (CONTACT_ID, CUSTOMER_ID, CONTACT_NAME, DESIGNATION, EMAIL) "
                "  VALUES (v_cid, :1, :2, :3, :4); "
                "  INSERT INTO MCP_APP.CONTACT_DETAILS "
                "    (CONTACT_DETAIL_ID, CONTACT_ID, PHONE_NUMBER, ALTERNATE_EMAIL) "
                "  VALUES (SEQ_CONTACT_DETAILS.NEXTVAL, v_cid, :5, :6); "
                "END;"
            ),
            "params": [
                customer_id, contact_name, designation or "",
                email, phone_number or None, alternate_email or None,
            ],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_CONTACT",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CONTACT", "add_customer_contact", "INSERT",
                        {"customer_number": customer_number, "email": email}, "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_contact_email(
    contact_id: int,
    new_email: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update CONTACT.EMAIL for a given contact_id after approval."""
    if not new_email or not new_email.strip():
        return _validation_error("new_email is required")

    conn = await get_connection()
    try:
        current = await _current_value(
            conn, "SELECT EMAIL FROM MCP_APP.CONTACT WHERE CONTACT_ID = :1",
            [int(contact_id)])
        if current is not None and str(current).strip().lower() == new_email.strip().lower():
            return _no_change(f"Contact {contact_id} email", current)

        new_val = json.dumps({
            "sql": "UPDATE MCP_APP.CONTACT SET EMAIL = :2 WHERE CONTACT_ID = :1",
            "params": [int(contact_id), new_email],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="UPDATE_CONTACT_EMAIL",
            action_type="UPDATE",
            old_value=json.dumps({"contact_id": contact_id, "old_email": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CONTACT", "update_contact_email", "UPDATE",
                        {"contact_id": contact_id, "new_email": new_email}, "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": new_email})
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group D: Account ──────────────────────────────────────────────────────────

async def create_account(
    customer_number: str,
    account_name: str,
    currency_code: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Create a new account via ACCOUNT_PKG.CREATE_ACCOUNT after approval.
    Billing cycle defaults to MONTHLY (hardcoded in Oracle package).
    """
    if not account_name or not account_name.strip():
        return _validation_error("account_name is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        currency_id = await resolve_currency_code(conn, currency_code)

        seq_rows = await _exec(
            conn,
            "SELECT 'ACC-' || LPAD(SEQ_ACCOUNT.NEXTVAL, 6, '0') AS account_number FROM DUAL"
        )
        account_number = seq_rows[0]["account_number"]

        new_val = json.dumps({
            "params": [customer_id, account_number, account_name, currency_id]
        })
        req = await create_approval_request(
            conn,
            package_name="ACCOUNT_PKG",
            procedure_name="CREATE_ACCOUNT",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "ACCOUNT_PKG", "create_account", "INSERT",
                        {"customer_number": customer_number, "account_number": account_number},
                        "SUCCESS")
        return _ok({**req, "account_number": account_number})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_account_status(
    account_number: str,
    new_status: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update ACCOUNT.STATUS via ACCOUNT_PKG.UPDATE_ACCOUNT_STATUS after approval."""
    if not new_status or not new_status.strip():
        return _validation_error("new_status is required")

    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        target = new_status.upper()
        current = await _current_value(
            conn, "SELECT STATUS FROM MCP_APP.ACCOUNT WHERE ACCOUNT_ID = :1",
            [account_id])
        if current is not None and str(current).upper() == target:
            return _no_change(f"Account {account_number} status", current)

        new_val = json.dumps({"params": [account_id, target]})
        req = await create_approval_request(
            conn,
            package_name="ACCOUNT_PKG",
            procedure_name="UPDATE_ACCOUNT_STATUS",
            action_type="UPDATE",
            old_value=json.dumps({"account_number": account_number, "old_status": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "ACCOUNT_PKG", "update_account_status", "UPDATE",
                        {"account_number": account_number, "new_status": new_status},
                        "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": target})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def set_account_billable(
    account_number: str,
    billable_flag: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update ACCOUNT_DETAILS.BILLABLE_FLAG ('Y' or 'N') after approval."""
    flag = (billable_flag or "").upper().strip()
    if flag not in ("Y", "N"):
        return _validation_error("billable_flag must be 'Y' or 'N'")

    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        current = await _current_value(
            conn,
            "SELECT BILLABLE_FLAG FROM MCP_APP.ACCOUNT_DETAILS WHERE ACCOUNT_ID = :1",
            [account_id])
        if current is not None and str(current).upper() == flag:
            return _no_change(f"Account {account_number} billable flag", current)

        new_val = json.dumps({
            "sql": "UPDATE MCP_APP.ACCOUNT_DETAILS SET BILLABLE_FLAG = :2 WHERE ACCOUNT_ID = :1",
            "params": [account_id, flag],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="SET_ACCOUNT_BILLABLE",
            action_type="UPDATE",
            old_value=json.dumps({"account_number": account_number, "old_flag": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "ACCOUNT_DETAILS", "set_account_billable", "UPDATE",
                        {"account_number": account_number, "billable_flag": flag},
                        "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": flag})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_account_currency(
    account_number: str,
    currency_code: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Change an account's billing currency (ACCOUNT.CURRENCY_ID) after approval."""
    if not currency_code or not currency_code.strip():
        return _validation_error("currency_code is required")

    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        currency_id = await resolve_currency_code(conn, currency_code)
        target = currency_code.upper()
        current = await _current_value(conn, """
            SELECT cur.CURRENCY_CODE
            FROM   MCP_APP.ACCOUNT a
            JOIN   MCP_APP.CURRENCY cur ON cur.CURRENCY_ID = a.CURRENCY_ID
            WHERE  a.ACCOUNT_ID = :1
        """, [account_id])
        if current is not None and str(current).upper() == target:
            return _no_change(f"Account {account_number} currency", current)

        new_val = json.dumps({
            "sql": "UPDATE MCP_APP.ACCOUNT SET CURRENCY_ID = :2 WHERE ACCOUNT_ID = :1",
            "params": [account_id, currency_id],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="UPDATE_ACCOUNT_CURRENCY",
            action_type="UPDATE",
            old_value=json.dumps({"account_number": account_number, "old_currency": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "ACCOUNT", "update_account_currency", "UPDATE",
                        {"account_number": account_number, "currency_code": target},
                        "SUCCESS")
        return _ok({**req, "current_value": current, "requested_value": target})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group E: Products ─────────────────────────────────────────────────────────

async def assign_product_to_account(
    customer_number: str,
    account_number: str,
    product_code: str,
    start_date: str = "",
    end_date: str = "",
    requested_by: str = "mcp_user",
) -> dict:
    """Insert a CUSTOMER_PRODUCT_DETAILS row after approval.
    Resolves all three codes before creating the request.
    """
    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        account_id = await resolve_account_number(conn, account_number)
        product_id = await resolve_product_code(conn, product_code)

        existing = await _current_value(conn, """
            SELECT 1 FROM MCP_APP.CUSTOMER_PRODUCT_DETAILS
            WHERE ACCOUNT_ID = :1 AND PRODUCT_ID = :2 AND STATUS = 'ACTIVE'
            FETCH FIRST 1 ROW ONLY
        """, [account_id, product_id])
        if existing is not None:
            return _no_change_msg(
                f"Product '{product_code}' is already actively assigned to "
                f"account '{account_number}' - no change needed.")

        # Build dynamic SQL for optional date params
        params: list = [customer_id, account_id, product_id]
        if start_date:
            start_sql = "TO_DATE(:4, 'YYYY-MM-DD')"
            params.append(start_date)
        else:
            start_sql = "SYSDATE"

        end_pos = len(params) + 1
        if end_date:
            end_sql = f"TO_DATE(:{end_pos}, 'YYYY-MM-DD')"
            params.append(end_date)
        else:
            end_sql = "NULL"

        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.CUSTOMER_PRODUCT_DETAILS "
                "(CUST_PRODUCT_ID, CUSTOMER_ID, ACCOUNT_ID, PRODUCT_ID, "
                f" START_DATE, END_DATE, STATUS) "
                f"VALUES (SEQ_CUST_PRODUCT.NEXTVAL, :1, :2, :3, {start_sql}, {end_sql}, 'ACTIVE')"
            ),
            "params": params,
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="ASSIGN_PRODUCT",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CUSTOMER_PRODUCT_DETAILS", "assign_product_to_account",
                        "INSERT",
                        {"account_number": account_number, "product_code": product_code},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def terminate_customer_product(
    customer_number: str,
    product_code: str,
    end_date: str = "",
    requested_by: str = "mcp_user",
) -> dict:
    """Set CUSTOMER_PRODUCT_DETAILS.STATUS='TERMINATED' after approval."""
    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        product_id = await resolve_product_code(conn, product_code)

        rows = await _exec(conn, """
            SELECT CUST_PRODUCT_ID FROM MCP_APP.CUSTOMER_PRODUCT_DETAILS
            WHERE  CUSTOMER_ID = :1 AND PRODUCT_ID = :2 AND STATUS = 'ACTIVE'
            FETCH FIRST 1 ROW ONLY
        """, [customer_id, product_id])
        if not rows:
            return _no_change_msg(
                f"Product '{product_code}' is not active for customer "
                f"'{customer_number}' - nothing to terminate.")

        cust_product_id = rows[0]["cust_product_id"]
        end_clause = f"TO_DATE(:2, 'YYYY-MM-DD')" if end_date else "SYSDATE"
        params = [cust_product_id]
        if end_date:
            params.append(end_date)

        new_val = json.dumps({
            "sql": (
                "UPDATE MCP_APP.CUSTOMER_PRODUCT_DETAILS "
                f"SET STATUS='TERMINATED', END_DATE={end_clause} "
                "WHERE CUST_PRODUCT_ID = :1"
            ),
            "params": params,
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="TERMINATE_PRODUCT",
            action_type="UPDATE",
            old_value=json.dumps({"cust_product_id": cust_product_id}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CUSTOMER_PRODUCT_DETAILS", "terminate_customer_product",
                        "UPDATE",
                        {"customer_number": customer_number, "product_code": product_code},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group F: Billing ──────────────────────────────────────────────────────────

async def create_bill(
    account_number: str,
    bill_amount: float,
    tax_amount: float,
    currency_code: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Generate a bill via BILLING_PKG.GENERATE_BILL after approval.
    approve_request will include the generated INVOICE_NUMBER in dml_result.post_query_result.
    """
    if bill_amount is None or bill_amount <= 0:
        return _validation_error("bill_amount must be positive")
    if tax_amount is None or tax_amount < 0:
        return _validation_error("tax_amount must be non-negative")

    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        currency_id = await resolve_currency_code(conn, currency_code)

        new_val = json.dumps({
            "params": [account_id, bill_amount, tax_amount, currency_id],
            "post_query": {
                "sql": (
                    "SELECT INVOICE_NUMBER, BILL_SUMMARY_ID "
                    "FROM MCP_APP.BILL_SUMMARY "
                    "WHERE ACCOUNT_ID = :1 "
                    "ORDER BY BILL_SUMMARY_ID DESC "
                    "FETCH FIRST 1 ROW ONLY"
                ),
                "params": [account_id],
            },
        })
        req = await create_approval_request(
            conn,
            package_name="BILLING_PKG",
            procedure_name="GENERATE_BILL",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "BILLING_PKG", "create_bill", "INSERT",
                        {"account_number": account_number, "bill_amount": bill_amount},
                        "SUCCESS")
        return _ok({
            **req,
            "note": "INVOICE_NUMBER available in dml_result.post_query_result after approval",
        })
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def update_bill_status(
    invoice_number: str,
    new_status: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Update BILL_SUMMARY.BILL_STATUS via BILLING_PKG.UPDATE_BILL_STATUS after approval."""
    if not new_status or not new_status.strip():
        return _validation_error("new_status is required")

    conn = await get_connection()
    try:
        rows = await _exec(conn,
            "SELECT BILL_SUMMARY_ID, BILL_STATUS FROM MCP_APP.BILL_SUMMARY "
            "WHERE UPPER(INVOICE_NUMBER) = UPPER(:1)",
            [invoice_number])
        if not rows:
            return _not_found(f"Invoice '{invoice_number}' not found")
        bill_summary_id = rows[0]["bill_summary_id"]
        target = new_status.upper()
        current = rows[0].get("bill_status")
        if current is not None and str(current).upper() == target:
            return _no_change(f"Invoice {invoice_number} status", current)

        new_val = json.dumps({"params": [bill_summary_id, target]})
        req = await create_approval_request(
            conn,
            package_name="BILLING_PKG",
            procedure_name="UPDATE_BILL_STATUS",
            action_type="UPDATE",
            old_value=json.dumps({"invoice_number": invoice_number, "old_status": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "BILLING_PKG", "update_bill_status", "UPDATE",
                        {"invoice_number": invoice_number, "new_status": new_status},
                        "SUCCESS")
        return _ok({**req, "invoice_number": invoice_number,
                    "current_value": current, "requested_value": target})
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def create_billing_adjustment(
    invoice_number: str,
    account_number: str,
    adjustment_type: str,
    adjustment_amount: float,
    reason: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Create a billing adjustment via BILLING_ADJUSTMENT_PKG.CREATE_ADJUSTMENT."""
    if adjustment_amount is None or adjustment_amount <= 0:
        return _validation_error("adjustment_amount must be a positive number")
    if not reason or not reason.strip():
        return _validation_error("reason is required")

    conn = await get_connection()
    try:
        rows = await _exec(conn,
            "SELECT BILL_SUMMARY_ID FROM MCP_APP.BILL_SUMMARY "
            "WHERE UPPER(INVOICE_NUMBER) = UPPER(:1)",
            [invoice_number])
        if not rows:
            return _not_found(f"Invoice '{invoice_number}' not found")
        bill_summary_id = rows[0]["bill_summary_id"]

        account_id = await resolve_account_number(conn, account_number)

        new_val = json.dumps({
            "params": [
                bill_summary_id, account_id,
                adjustment_type.upper(), adjustment_amount,
                reason, requested_by,
            ]
        })
        req = await create_approval_request(
            conn,
            package_name="BILLING_ADJUSTMENT_PKG",
            procedure_name="CREATE_ADJUSTMENT",
            action_type="INSERT",
            old_value=json.dumps({"invoice_number": invoice_number}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "BILLING_ADJUSTMENT_PKG", "create_billing_adjustment",
                        "INSERT",
                        {"invoice_number": invoice_number,
                         "adjustment_amount": adjustment_amount},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group G: Costed Event ─────────────────────────────────────────────────────

async def ingest_costed_event(
    account_number: str,
    event_dtm: str,
    in_bits: int = 0,
    out_bits: int = 0,
    speed_mbps: float = 0.0,
    bandwidth_mbps: float = 0.0,
    event_type: str = "DATA_USAGE",
    source_system: str = "USAGE_COLLECTOR",
    requested_by: str = "mcp_user",
) -> dict:
    """Insert a COSTED_EVENT row after approval."""
    if not event_dtm:
        return _validation_error("event_dtm is required (format: YYYY-MM-DD HH24:MI:SS)")

    conn = await get_connection()
    try:
        account_id = await resolve_account_number(conn, account_number)
        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.COSTED_EVENT "
                "(EVENT_ID, ACCOUNT_ID, ACCOUNT_NUM, EVENT_DTM, CREATED_DTM, "
                " IN_BITS, OUT_BITS, SPEED_MBPS, BANDWIDTH_MBPS, "
                " EVENT_TYPE, SOURCE_SYSTEM, STATUS) "
                "VALUES (SEQ_COSTED_EVENT.NEXTVAL, :1, :2, "
                "TO_TIMESTAMP(:3, 'YYYY-MM-DD HH24:MI:SS'), SYSTIMESTAMP, "
                ":4, :5, :6, :7, :8, :9, 'SUCCESS')"
            ),
            "params": [
                account_id, account_number, event_dtm,
                int(in_bits), int(out_bits),
                float(speed_mbps), float(bandwidth_mbps),
                event_type or "DATA", source_system or "MANUAL",
            ],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_COSTED_EVENT",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "COSTED_EVENT", "ingest_costed_event", "INSERT",
                        {"account_number": account_number, "event_dtm": event_dtm},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group I: Service Requests & Notes ─────────────────────────────────────────

async def create_service_request(
    customer_number: str,
    request_type: str,
    priority: str,
    description: str,
    raised_by: str,
    account_number: str = "",
    requested_by: str = "mcp_user",
) -> dict:
    """Create a service request via SERVICE_REQUEST_PKG.CREATE_REQUEST after approval."""
    if not description or not description.strip():
        return _validation_error("description is required")
    if not raised_by or not raised_by.strip():
        return _validation_error("raised_by is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        account_id: int | None = None
        if account_number:
            account_id = await resolve_account_number(conn, account_number)

        new_val = json.dumps({
            "params": [
                customer_id, account_id,
                request_type.upper(), priority.upper(),
                description, raised_by,
            ]
        })
        req = await create_approval_request(
            conn,
            package_name="SERVICE_REQUEST_PKG",
            procedure_name="CREATE_REQUEST",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG", "create_service_request", "INSERT",
                        {"customer_number": customer_number, "request_type": request_type},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def assign_service_request(
    request_id: int,
    assigned_to: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Assign a service request via SERVICE_REQUEST_PKG.ASSIGN_REQUEST after approval."""
    if not assigned_to or not assigned_to.strip():
        return _validation_error("assigned_to is required")

    conn = await get_connection()
    try:
        current = await _current_value(
            conn,
            "SELECT ASSIGNED_TO FROM MCP_APP.SERVICE_REQUEST WHERE REQUEST_ID = :1",
            [int(request_id)])
        if current is not None and str(current).upper() == assigned_to.upper():
            return _no_change(f"Service request {request_id} assignee", current)

        new_val = json.dumps({"params": [int(request_id), assigned_to]})
        req = await create_approval_request(
            conn,
            package_name="SERVICE_REQUEST_PKG",
            procedure_name="ASSIGN_REQUEST",
            action_type="UPDATE",
            old_value=json.dumps({"request_id": request_id, "old_assignee": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG", "assign_service_request", "UPDATE",
                        {"request_id": request_id, "assigned_to": assigned_to},
                        "SUCCESS")
        return _ok(req)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def resolve_service_request(
    request_id: int,
    resolution_notes: str,
    resolved_by: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Resolve a service request via SERVICE_REQUEST_PKG.RESOLVE_REQUEST after approval."""
    if not resolution_notes or not resolution_notes.strip():
        return _validation_error("resolution_notes is required")
    if not resolved_by or not resolved_by.strip():
        return _validation_error("resolved_by is required")

    conn = await get_connection()
    try:
        current = await _current_value(
            conn,
            "SELECT STATUS FROM MCP_APP.SERVICE_REQUEST WHERE REQUEST_ID = :1",
            [int(request_id)])
        if current is not None and str(current).upper() in ("RESOLVED", "CLOSED"):
            return _no_change_msg(
                f"Service request {request_id} is already {current} - no change needed.",
                current_value=current)

        new_val = json.dumps({"params": [int(request_id), resolution_notes, resolved_by]})
        req = await create_approval_request(
            conn,
            package_name="SERVICE_REQUEST_PKG",
            procedure_name="RESOLVE_REQUEST",
            action_type="UPDATE",
            old_value=json.dumps({"request_id": request_id, "old_status": current}),
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "SERVICE_REQUEST_PKG", "resolve_service_request", "UPDATE",
                        {"request_id": request_id}, "SUCCESS")
        return _ok(req)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def add_customer_note(
    customer_number: str,
    note_type: str,
    note_text: str,
    created_by: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Insert a CUSTOMER_NOTE row after approval."""
    if not note_text or not note_text.strip():
        return _validation_error("note_text is required")
    if not created_by or not created_by.strip():
        return _validation_error("created_by is required")

    conn = await get_connection()
    try:
        customer_id = await resolve_customer_number(conn, customer_number)
        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.CUSTOMER_NOTE "
                "(NOTE_ID, CUSTOMER_ID, NOTE_TYPE, NOTE_TEXT, CREATED_BY) "
                "VALUES (SEQ_CUSTOMER_NOTE.NEXTVAL, :1, :2, :3, :4)"
            ),
            "params": [customer_id, note_type or "GENERAL", note_text, created_by],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_NOTE",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CUSTOMER_NOTE", "add_customer_note", "INSERT",
                        {"customer_number": customer_number, "note_type": note_type},
                        "SUCCESS")
        return _ok(req)
    except ValueError as exc:
        return _not_found(exc)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── Group J: Currency ─────────────────────────────────────────────────────────

async def create_currency(
    currency_code: str,
    currency_name: str,
    requested_by: str = "mcp_user",
) -> dict:
    """Insert a new CURRENCY row after approval.
    Dispatching a duplicate currency_code will raise ORA-00001 (unique constraint)
    which is mapped to an error response by approve_request.
    """
    if not currency_code or not currency_code.strip():
        return _validation_error("currency_code is required")
    if not currency_name or not currency_name.strip():
        return _validation_error("currency_name is required")

    conn = await get_connection()
    try:
        existing = await _current_value(
            conn,
            "SELECT CURRENCY_CODE FROM MCP_APP.CURRENCY WHERE UPPER(CURRENCY_CODE) = UPPER(:1)",
            [currency_code])
        if existing is not None:
            return _no_change_msg(
                f"Currency '{currency_code.upper()}' already exists - no change needed.",
                current_value=existing)

        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.CURRENCY "
                "(CURRENCY_ID, CURRENCY_CODE, CURRENCY_NAME) "
                "VALUES (SEQ_CURRENCY.NEXTVAL, :1, :2)"
            ),
            "params": [currency_code.upper(), currency_name],
        })
        req = await create_approval_request(
            conn,
            package_name="DIRECT_SQL",
            procedure_name="INSERT_CURRENCY",
            action_type="INSERT",
            old_value=None,
            new_value=new_val,
            requested_by=requested_by,
        )
        await log_audit(_TOOL, "CURRENCY", "create_currency", "INSERT",
                        {"currency_code": currency_code}, "SUCCESS")
        return _ok(req)
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()
