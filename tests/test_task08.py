"""
TASK 08 — Product & Billing Read Tools (Groups E & F)
Unit tests: T08-01 through T08-10
"""
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch


# ── mock helpers ──────────────────────────────────────────────────────────────

def _make_conn_mock():
    conn = MagicMock()
    conn.close = AsyncMock()
    return conn


def _stack(exec_rows, resolvers: dict | None = None, callfunc_rows=None):
    """Build an ExitStack patching billing._exec, get_connection, log_audit,
    and optional resolvers.  If callfunc_rows is given, patch _callfunc_cursor
    to return it (for package-function tools)."""
    s = ExitStack()
    conn = _make_conn_mock()
    s.enter_context(
        patch("src.tools.billing.get_connection",
              new_callable=AsyncMock, return_value=conn))
    s.enter_context(
        patch("src.tools.billing._exec",
              new_callable=AsyncMock, side_effect=exec_rows))
    s.enter_context(
        patch("src.tools.billing.log_audit",
              new_callable=AsyncMock, return_value=True))
    if callfunc_rows is not None:
        s.enter_context(
            patch("src.tools.billing._callfunc_cursor",
                  new_callable=AsyncMock, return_value=callfunc_rows))
    for fname, retval in (resolvers or {}).items():
        if retval is None:
            s.enter_context(
                patch(f"src.tools.billing.{fname}",
                      new_callable=AsyncMock,
                      side_effect=ValueError("Not found")))
        else:
            s.enter_context(
                patch(f"src.tools.billing.{fname}",
                      new_callable=AsyncMock, return_value=retval))
    return s, conn


# ── T08-01: get_products active-only returns only STATUS=ACTIVE rows ──────────

@pytest.mark.asyncio
async def test_t08_01_get_products_active_only():
    rows = [
        {"product_id": 1, "product_code": "MPLS-STD",
         "product_name": "MPLS Standard", "product_type": "DATA",
         "status": "ACTIVE"},
        {"product_id": 2, "product_code": "VOICE-01",
         "product_name": "Voice", "product_type": "VOICE", "status": "ACTIVE"},
    ]
    with _stack([rows])[0]:
        from src.tools.billing import get_products
        result = await get_products(status="ACTIVE")
    assert result["success"] is True
    assert result["row_count"] == 2
    assert all(r["status"] == "ACTIVE" for r in result["data"])


# ── T08-02: get_product_by_code returns correct product ──────────────────────

@pytest.mark.asyncio
async def test_t08_02_get_product_by_code_found():
    rows = [{"product_id": 1, "product_code": "MPLS-STD",
             "product_name": "MPLS Standard", "product_type": "DATA",
             "status": "ACTIVE"}]
    with _stack([rows])[0]:
        from src.tools.billing import get_product_by_code
        result = await get_product_by_code("MPLS-STD")
    assert result["success"] is True
    assert result["data"]["product_code"] == "MPLS-STD"
    assert result["data"]["product_type"] == "DATA"


# ── T08-03: get_product_by_code unknown code returns None, not error ──────────

@pytest.mark.asyncio
async def test_t08_03_get_product_by_code_not_found():
    with _stack([[]])[0]:
        from src.tools.billing import get_product_by_code
        result = await get_product_by_code("NO-SUCH")
    assert result["success"] is True
    assert result["data"] is None
    assert result["row_count"] == 0


# ── T08-04: get_bills_by_account calls BILLING_PKG.GET_BILL_DETAILS ──────────

@pytest.mark.asyncio
async def test_t08_04_get_bills_by_account_package_call():
    bill_rows = [
        {"bill_summary_id": 1, "invoice_number": "INV-001",
         "billing_month": "2026-01-01", "bill_amount": 1000.0,
         "tax_amount": 200.0, "total_amount": 1200.0,
         "bill_status": "PAID", "currency_code": "USD"},
        {"bill_summary_id": 2, "invoice_number": "INV-002",
         "billing_month": "2026-02-01", "bill_amount": 900.0,
         "tax_amount": 180.0, "total_amount": 1080.0,
         "bill_status": "UNPAID", "currency_code": "USD"},
    ]
    with _stack([], {"resolve_account_number": 42},
                callfunc_rows=bill_rows)[0]:
        from src.tools.billing import get_bills_by_account
        result = await get_bills_by_account("ACC-001")
    assert result["success"] is True
    assert result["row_count"] == 2
    assert result["data"][0]["invoice_number"] == "INV-001"


# ── T08-05: get_bills_by_account status filter works ─────────────────────────

@pytest.mark.asyncio
async def test_t08_05_get_bills_by_account_status_filter():
    all_bills = [
        {"bill_summary_id": 1, "invoice_number": "INV-001",
         "billing_month": "2026-01-01", "bill_amount": 1000.0,
         "tax_amount": 200.0, "total_amount": 1200.0,
         "bill_status": "PAID", "currency_code": "USD"},
        {"bill_summary_id": 2, "invoice_number": "INV-002",
         "billing_month": "2026-02-01", "bill_amount": 900.0,
         "tax_amount": 180.0, "total_amount": 1080.0,
         "bill_status": "UNPAID", "currency_code": "USD"},
    ]
    with _stack([], {"resolve_account_number": 42},
                callfunc_rows=all_bills)[0]:
        from src.tools.billing import get_bills_by_account
        result = await get_bills_by_account("ACC-001", status="UNPAID")
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["bill_status"] == "UNPAID"


# ── T08-06: get_bill_by_invoice_number returns joined customer/account info ───

@pytest.mark.asyncio
async def test_t08_06_get_bill_by_invoice_number():
    rows = [
        {"bill_summary_id": 1, "invoice_number": "INV-001",
         "billing_month": "2026-01-01", "bill_amount": 1000.0,
         "tax_amount": 200.0, "total_amount": 1200.0,
         "bill_status": "PAID", "currency_code": "USD",
         "account_number": "ACC-001", "customer_number": "CUST-001"},
    ]
    with _stack([rows])[0]:
        from src.tools.billing import get_bill_by_invoice_number
        result = await get_bill_by_invoice_number("INV-001")
    assert result["success"] is True
    assert result["data"]["customer_number"] == "CUST-001"
    assert result["data"]["account_number"] == "ACC-001"
    assert result["data"]["total_amount"] == 1200.0


# ── T08-07: get_billing_summary_by_customer aggregates totals ────────────────

@pytest.mark.asyncio
async def test_t08_07_get_billing_summary_by_customer():
    summary = [{"customer_number": "CUST-001", "customer_name": "Acme Corp",
                "invoice_count": 12, "total_billed": 15000.0,
                "outstanding_amount": 2000.0, "paid_amount": 13000.0}]
    with _stack([summary], {"resolve_customer_number": 1})[0]:
        from src.tools.billing import get_billing_summary_by_customer
        result = await get_billing_summary_by_customer("CUST-001")
    assert result["success"] is True
    d = result["data"]
    assert d["invoice_count"] == 12
    assert d["total_billed"] == 15000.0
    assert d["outstanding_amount"] == 2000.0
    assert d["paid_amount"] == 13000.0


# ── T08-08: get_unpaid_bills excludes PAID and CANCELLED ─────────────────────

@pytest.mark.asyncio
async def test_t08_08_get_unpaid_bills_excludes_paid():
    rows = [
        {"bill_summary_id": 2, "invoice_number": "INV-002",
         "billing_month": "2026-02-01", "total_amount": 1080.0,
         "bill_status": "UNPAID", "currency_code": "USD",
         "account_number": "ACC-001", "customer_number": "CUST-001"},
    ]
    with _stack([rows])[0]:
        from src.tools.billing import get_unpaid_bills
        result = await get_unpaid_bills()
    assert result["success"] is True
    assert all(r["bill_status"] not in ("PAID", "CANCELLED")
               for r in result["data"])


# ── T08-09: get_monthly_revenue returns rows with month, total_revenue ────────

@pytest.mark.asyncio
async def test_t08_09_get_monthly_revenue_structure():
    rows = [
        {"month": "2026-05", "total_revenue": 120000.0, "invoice_count": 45},
        {"month": "2026-04", "total_revenue": 110000.0, "invoice_count": 42},
    ]
    with _stack([rows])[0]:
        from src.tools.billing import get_monthly_revenue
        result = await get_monthly_revenue(months=2)
    assert result["success"] is True
    assert result["row_count"] == 2
    row = result["data"][0]
    assert "month" in row
    assert "total_revenue" in row
    assert "invoice_count" in row


# ── T08-10: get_pending_adjustments calls package then falls back to SQL ──────

@pytest.mark.asyncio
async def test_t08_10_get_pending_adjustments_package():
    adj_rows = [
        {"adjustment_id": 1, "adjustment_type": "CREDIT",
         "adjustment_amount": -50.0, "reason": "Overcharge",
         "status": "PENDING", "requested_by": "agent1",
         "invoice_number": "INV-001", "account_number": "ACC-001"},
    ]
    with _stack([], callfunc_rows=adj_rows)[0]:
        from src.tools.billing import get_pending_adjustments
        result = await get_pending_adjustments()
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["status"] == "PENDING"


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t08_01_integration_get_products(db_conn):
    from src.tools.billing import get_products
    result = await get_products(status="ALL")
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t08_04_integration_bills_by_account(db_conn):
    from src.tools.billing import get_products, get_bills_by_account
    from src.tools.account import get_accounts_by_customer
    from src.tools.customer import search_customers
    custs = await search_customers(limit=1)
    if not custs["data"]:
        pytest.skip("No customers in DB")
    accs = await get_accounts_by_customer(custs["data"][0]["customer_number"])
    if not accs["data"]:
        pytest.skip("No accounts found")
    result = await get_bills_by_account(accs["data"][0]["account_number"])
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t08_07_integration_billing_summary(db_conn):
    from src.tools.customer import search_customers
    from src.tools.billing import get_billing_summary_by_customer
    custs = await search_customers(limit=1)
    if not custs["data"]:
        pytest.skip("No customers in DB")
    result = await get_billing_summary_by_customer(
        custs["data"][0]["customer_number"])
    assert result["success"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t08_09_integration_monthly_revenue(db_conn):
    from src.tools.billing import get_monthly_revenue
    result = await get_monthly_revenue(months=6)
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t08_10_integration_pending_adjustments(db_conn):
    from src.tools.billing import get_pending_adjustments
    result = await get_pending_adjustments()
    assert result["success"] is True
    assert isinstance(result["data"], list)
