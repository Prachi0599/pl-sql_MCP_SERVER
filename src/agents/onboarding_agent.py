"""onboarding_agent — Full customer onboarding via 5 sequential approval requests.

Pattern B: hardcoded 5-step sequential flow, no GPT-4o.

Exposes a single public coroutine:
    run(params: dict) -> dict

Flow:
  0. Pydantic validation → VALIDATION_ERROR on failure (no DB call)
  1. create_customer       (via _writes) → extracts customer_number
  2-5. Build approval requests directly, using SQL subqueries so that
       customer_id / account_id are resolved at approval-execution time,
       not at request-creation time. This allows all 5 requests to be
       queued even though the customer and account do not yet exist in
       the CUSTOMER / ACCOUNT tables (they are still PENDING approval).

Each step produces a PENDING approval request.
On any step failure: stop immediately, return partial result.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from src.db.pool import get_connection
from src.db.resolvers import resolve_currency_code, resolve_product_code
from src.tools import writes as _writes
from src.tools.approval import create_approval_request
from src.utils.audit import log_audit

_AGENT = "onboarding_agent"

_STEP_DESCRIPTIONS = [
    "Create customer record",
    "Add customer address",
    "Add customer contact",
    "Create account",
    "Assign product to account",
]


class OnboardingParams(BaseModel):
    customer_name:      str
    company_code:       str
    customer_type_code: str
    address_type:       str
    address_line1:      str
    city:               str
    country:            str
    contact_name:       str
    designation:        str
    email:              str
    phone_number:       str = ""
    account_name:       str
    currency_code:      str
    product_code:       str
    start_date:         str = ""
    requested_by:       str = "mcp_user"


# ── Step helpers (private) ────────────────────────────────────────────────────
# Each helper opens its own connection and builds a DIRECT_SQL approval request.
# SQL subqueries defer ID resolution to approval-execution time so that the
# customer / account do not need to exist in the DB when the requests are created.

async def _step2_address(customer_number: str, p: OnboardingParams) -> dict:
    conn = await get_connection()
    try:
        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.ADDRESS "
                "(ADDRESS_ID, CUSTOMER_ID, ADDRESS_TYPE, ADDRESS_LINE1, "
                " CITY, STATE, COUNTRY, POSTAL_CODE) "
                "VALUES (SEQ_ADDRESS.NEXTVAL, "
                "  (SELECT CUSTOMER_ID FROM MCP_APP.CUSTOMER "
                "   WHERE CUSTOMER_NUMBER = :1), "
                "  :2, :3, :4, :5, :6, :7)"
            ),
            "params": [
                customer_number,
                p.address_type or "BILLING",
                p.address_line1,
                p.city,
                None,
                p.country,
                None,
            ],
        })
        req = await create_approval_request(
            conn, "DIRECT_SQL", "INSERT_ADDRESS", "INSERT",
            None, new_val, p.requested_by,
        )
        return {"success": True, **req}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    finally:
        await conn.close()


async def _step3_contact(customer_number: str, p: OnboardingParams) -> dict:
    conn = await get_connection()
    try:
        new_val = json.dumps({
            "sql": (
                "DECLARE v_cid NUMBER; v_custid NUMBER; "
                "BEGIN "
                "  SELECT CUSTOMER_ID INTO v_custid FROM MCP_APP.CUSTOMER "
                "    WHERE CUSTOMER_NUMBER = :1; "
                "  SELECT SEQ_CONTACT.NEXTVAL INTO v_cid FROM DUAL; "
                "  INSERT INTO MCP_APP.CONTACT "
                "    (CONTACT_ID, CUSTOMER_ID, CONTACT_NAME, DESIGNATION, EMAIL) "
                "  VALUES (v_cid, v_custid, :2, :3, :4); "
                "  INSERT INTO MCP_APP.CONTACT_DETAILS "
                "    (CONTACT_DETAIL_ID, CONTACT_ID, PHONE_NUMBER, ALTERNATE_EMAIL) "
                "  VALUES (SEQ_CONTACT_DETAILS.NEXTVAL, v_cid, :5, :6); "
                "END;"
            ),
            "params": [
                customer_number,
                p.contact_name,
                p.designation or "",
                p.email,
                p.phone_number or None,
                None,
            ],
        })
        req = await create_approval_request(
            conn, "DIRECT_SQL", "INSERT_CONTACT", "INSERT",
            None, new_val, p.requested_by,
        )
        return {"success": True, **req}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    finally:
        await conn.close()


async def _step4_account(customer_number: str, p: OnboardingParams) -> dict:
    """
    Pre-consumes SEQ_ACCOUNT to reserve the account_number string; the actual
    ACCOUNT_ID is generated again at INSERT time (by SEQ_ACCOUNT.NEXTVAL inside
    the stored SQL). The pre-consumed value is stored as ACCOUNT_NUMBER, which
    step 5 later looks up via a subquery.
    """
    conn = await get_connection()
    try:
        currency_id = await resolve_currency_code(conn, p.currency_code)
        # Pre-reserve the account_number so step 5 can reference it
        with conn.cursor() as cur:
            await cur.execute(
                "SELECT 'ACC-' || LPAD(SEQ_ACCOUNT.NEXTVAL, 6, '0') FROM DUAL"
            )
            row = await cur.fetchone()
        account_number: str = row[0]

        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.ACCOUNT "
                "(ACCOUNT_ID, CUSTOMER_ID, ACCOUNT_NUMBER, ACCOUNT_NAME, "
                " CURRENCY_ID, STATUS, BILLING_CYCLE) "
                "VALUES (SEQ_ACCOUNT.NEXTVAL, "
                "  (SELECT CUSTOMER_ID FROM MCP_APP.CUSTOMER "
                "   WHERE CUSTOMER_NUMBER = :1), "
                "  :2, :3, :4, 'ACTIVE', 'MONTHLY')"
            ),
            "params": [customer_number, account_number, p.account_name, currency_id],
        })
        req = await create_approval_request(
            conn, "DIRECT_SQL", "INSERT_ACCOUNT", "INSERT",
            None, new_val, p.requested_by,
        )
        return {"success": True, **req, "account_number": account_number}
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    finally:
        await conn.close()


async def _step5_product(customer_number: str, account_number: str,
                         p: OnboardingParams) -> dict:
    conn = await get_connection()
    try:
        product_id = await resolve_product_code(conn, p.product_code)
        start_sql = "TO_DATE(:4, 'YYYY-MM-DD')" if p.start_date else "SYSDATE"
        params: list = [customer_number, account_number, product_id]
        if p.start_date:
            params.append(p.start_date)

        new_val = json.dumps({
            "sql": (
                "INSERT INTO MCP_APP.CUSTOMER_PRODUCT_DETAILS "
                "(CUST_PRODUCT_ID, CUSTOMER_ID, ACCOUNT_ID, PRODUCT_ID, "
                " START_DATE, END_DATE, STATUS) "
                f"VALUES (SEQ_CUST_PRODUCT.NEXTVAL, "
                "  (SELECT CUSTOMER_ID FROM MCP_APP.CUSTOMER "
                "   WHERE CUSTOMER_NUMBER = :1), "
                "  (SELECT ACCOUNT_ID FROM MCP_APP.ACCOUNT "
                "   WHERE ACCOUNT_NUMBER = :2), "
                f"  :3, {start_sql}, NULL, 'ACTIVE')"
            ),
            "params": params,
        })
        req = await create_approval_request(
            conn, "DIRECT_SQL", "ASSIGN_PRODUCT", "INSERT",
            None, new_val, p.requested_by,
        )
        return {"success": True, **req}
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    finally:
        await conn.close()


# ── Main entry point ──────────────────────────────────────────────────────────

async def run(params: dict) -> dict:
    """
    Onboard a new customer in 5 sequential approval-request steps.

    Returns:
        {
          "success": bool,              # True only if all 5 steps complete
          "steps": [
            {
              "step": int,              # 1–5
              "description": str,
              "request_id": int | None, # None on failure
              "status": "PENDING" | "FAILED",
            },
            ...
          ],
          "customer_number": str | None,
          "account_number": str | None,
          "total_steps": 5,
          "steps_completed": int,
        }
    """
    # ── Step 0: Pydantic validation ───────────────────────────────────────────
    try:
        p = OnboardingParams(**params)
    except ValidationError as exc:
        return {
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "message": str(exc),
            "steps": [],
            "customer_number": None,
            "account_number": None,
            "total_steps": 5,
            "steps_completed": 0,
        }

    steps: list[dict] = []
    customer_number: str | None = None
    account_number: str | None = None

    # ── Step 1: create_customer ───────────────────────────────────────────────
    r1 = await _writes.create_customer(
        customer_name=p.customer_name,
        company_code=p.company_code,
        customer_type_code=p.customer_type_code,
        requested_by=p.requested_by,
    )
    if not r1.get("success"):
        steps.append({
            "step": 1, "description": _STEP_DESCRIPTIONS[0],
            "request_id": None, "status": "FAILED",
            "error": r1.get("message", "Unknown error"),
        })
        return _partial(steps, customer_number, account_number)

    customer_number = r1.get("customer_number")
    steps.append({
        "step": 1, "description": _STEP_DESCRIPTIONS[0],
        "request_id": r1.get("request_id"), "status": "PENDING",
    })

    # ── Step 2: add customer address ──────────────────────────────────────────
    r2 = await _step2_address(customer_number, p)
    if not r2.get("success"):
        steps.append({
            "step": 2, "description": _STEP_DESCRIPTIONS[1],
            "request_id": None, "status": "FAILED",
            "error": r2.get("message", "Unknown error"),
        })
        return _partial(steps, customer_number, account_number)

    steps.append({
        "step": 2, "description": _STEP_DESCRIPTIONS[1],
        "request_id": r2.get("request_id"), "status": "PENDING",
    })

    # ── Step 3: add customer contact ──────────────────────────────────────────
    r3 = await _step3_contact(customer_number, p)
    if not r3.get("success"):
        steps.append({
            "step": 3, "description": _STEP_DESCRIPTIONS[2],
            "request_id": None, "status": "FAILED",
            "error": r3.get("message", "Unknown error"),
        })
        return _partial(steps, customer_number, account_number)

    steps.append({
        "step": 3, "description": _STEP_DESCRIPTIONS[2],
        "request_id": r3.get("request_id"), "status": "PENDING",
    })

    # ── Step 4: create account ────────────────────────────────────────────────
    r4 = await _step4_account(customer_number, p)
    if not r4.get("success"):
        steps.append({
            "step": 4, "description": _STEP_DESCRIPTIONS[3],
            "request_id": None, "status": "FAILED",
            "error": r4.get("message", "Unknown error"),
        })
        return _partial(steps, customer_number, account_number)

    account_number = r4.get("account_number")
    steps.append({
        "step": 4, "description": _STEP_DESCRIPTIONS[3],
        "request_id": r4.get("request_id"), "status": "PENDING",
    })

    # ── Step 5: assign product to account ─────────────────────────────────────
    r5 = await _step5_product(customer_number, account_number, p)
    if not r5.get("success"):
        steps.append({
            "step": 5, "description": _STEP_DESCRIPTIONS[4],
            "request_id": None, "status": "FAILED",
            "error": r5.get("message", "Unknown error"),
        })
        return _partial(steps, customer_number, account_number)

    steps.append({
        "step": 5, "description": _STEP_DESCRIPTIONS[4],
        "request_id": r5.get("request_id"), "status": "PENDING",
    })

    # ── All 5 steps queued ────────────────────────────────────────────────────
    await log_audit(
        _AGENT, "", p.customer_name[:100], "WRITE",
        {
            "customer_name": p.customer_name,
            "customer_number": customer_number,
            "account_number": account_number,
            "steps_completed": 5,
        },
        "SUCCESS",
    )

    return {
        "success": True,
        "steps": steps,
        "customer_number": customer_number,
        "account_number": account_number,
        "total_steps": 5,
        "steps_completed": 5,
    }


def _partial(steps: list[dict], customer_number: str | None,
             account_number: str | None) -> dict:
    steps_completed = sum(1 for s in steps if s["status"] == "PENDING")
    return {
        "success": False,
        "steps": steps,
        "customer_number": customer_number,
        "account_number": account_number,
        "total_steps": 5,
        "steps_completed": steps_completed,
    }
