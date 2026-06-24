"""
TASK 06 — Customer Read Tools (Group B read)
Unit tests: T06-01 through T06-09
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn_mock(rows_sequence):
    """Mock get_connection + _exec to return *rows_sequence* in order."""
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    return mock_conn


def _patch_exec(side_effect_rows):
    """Patch customer._exec and get_connection; side_effect_rows is a list of return values."""
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    exec_mock = AsyncMock(side_effect=side_effect_rows)
    conn_patch = patch("src.tools.customer.get_connection",
                       new_callable=AsyncMock, return_value=mock_conn)
    exec_patch = patch("src.tools.customer._exec", exec_mock)
    audit_patch = patch("src.tools.customer.log_audit", new_callable=AsyncMock)
    return conn_patch, exec_patch, audit_patch, exec_mock


# ── T06-01: search_customers name match is case-insensitive LIKE ──────────────

@pytest.mark.asyncio
async def test_t06_01_search_customers_case_insensitive():
    cp, ep, ap, em = _patch_exec([[
        {"customer_id": 1, "customer_number": "CUST-001",
         "customer_name": "Acme Corp", "status": "ACTIVE"}
    ]])
    with cp, ep, ap:
        from src.tools.customer import search_customers
        result = await search_customers(name="acme")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T06-02: search_customers no params returns up to 50 rows ─────────────────

@pytest.mark.asyncio
async def test_t06_02_search_customers_default_limit():
    rows = [{"customer_id": i} for i in range(50)]
    cp, ep, ap, em = _patch_exec([rows])
    with cp, ep, ap:
        from src.tools.customer import search_customers
        result = await search_customers()
    assert result["success"] is True
    assert result["row_count"] == 50


# ── T06-03: search_customers limit=10 returns exactly 10 rows ─────────────────

@pytest.mark.asyncio
async def test_t06_03_search_customers_limit():
    rows = [{"customer_id": i} for i in range(10)]
    cp, ep, ap, em = _patch_exec([rows])
    with cp, ep, ap:
        from src.tools.customer import search_customers
        result = await search_customers(limit=10)
    assert result["row_count"] == 10


# ── T06-04: search_customers offset=10 returns next page ─────────────────────

@pytest.mark.asyncio
async def test_t06_04_search_customers_pagination():
    page2 = [{"customer_id": i} for i in range(10, 20)]
    cp, ep, ap, em = _patch_exec([page2])
    with cp, ep, ap:
        from src.tools.customer import search_customers
        result = await search_customers(limit=10, offset=10)
    assert result["row_count"] == 10
    # Verify offset was passed in SQL params
    call_params = em.call_args[0][2]  # (conn, sql, params)
    assert 10 in call_params  # offset value


# ── T06-05: get_customer_by_number returns joined fields ─────────────────────

@pytest.mark.asyncio
async def test_t06_05_get_customer_by_number_joined():
    rows = [{"customer_id": 1, "customer_number": "CUST-001",
             "customer_name": "Acme", "status": "ACTIVE",
             "customer_type_name": "Enterprise", "company_code": "EMEA-01",
             "company_name": "EMEA Corp", "created_dtm": "2024-01-01"}]
    cp, ep, ap, em = _patch_exec([rows])
    with cp, ep, ap:
        from src.tools.customer import get_customer_by_number
        result = await get_customer_by_number("CUST-001")
    assert result["success"] is True
    assert result["data"]["customer_type_name"] == "Enterprise"
    assert result["data"]["company_name"] == "EMEA Corp"


# ── T06-06: get_customer_360 returns full nested structure ────────────────────

@pytest.mark.asyncio
async def test_t06_06_get_customer_360_structure():
    cust = [{"customer_id": 1, "customer_number": "CUST-001",
             "customer_name": "Acme", "status": "ACTIVE",
             "customer_type_name": "Enterprise", "company_code": "EMEA-01"}]
    addrs = [{"address_id": 1, "address_type": "BILLING",
              "address_line1": "1 Main St", "city": "London", "country": "UK"}]
    cons = [{"contact_id": 1, "contact_name": "Jane Doe",
             "designation": "CFO", "email": "j@acme.com", "phone_number": "+44"}]
    accs = [{"account_id": 1, "account_number": "ACC-001",
             "status": "ACTIVE", "billing_cycle": "MONTHLY", "currency_code": "GBP"}]
    prods = [{"product_code": "PROD-MPLS", "product_name": "MPLS",
              "product_type": "DATA", "status": "ACTIVE",
              "start_date": "2024-01-01", "end_date": None}]
    bills = [{"invoice_number": "INV-001", "bill_amount": 1000,
              "total_amount": 1100, "bill_status": "UNPAID", "billing_month": "2024-06"}]

    cp, ep, ap, em = _patch_exec([cust, addrs, cons, accs, prods, bills])
    with cp, ep, ap:
        from src.tools.customer import get_customer_360
        result = await get_customer_360("CUST-001")

    assert result["success"] is True
    d = result["data"]
    assert "customer" in d
    assert "addresses" in d
    assert "contacts" in d
    assert "accounts" in d
    assert "products" in d
    assert "latest_bill" in d
    assert d["latest_bill"]["invoice_number"] == "INV-001"


# ── T06-07: get_customer_360 unknown customer returns not-found ───────────────

@pytest.mark.asyncio
async def test_t06_07_get_customer_360_not_found():
    cp, ep, ap, em = _patch_exec([[]])  # empty customer lookup
    with cp, ep, ap:
        from src.tools.customer import get_customer_360
        result = await get_customer_360("CUST-GHOST")
    assert result["success"] is True
    assert result["data"] is None
    assert result["row_count"] == 0


# ── T06-08: get_customers_by_company returns correct company ──────────────────

@pytest.mark.asyncio
async def test_t06_08_get_customers_by_company():
    rows = [{"customer_id": 1, "customer_number": "CUST-001",
             "customer_name": "Acme", "status": "ACTIVE"}]
    cp, ep, ap, em = _patch_exec([rows])
    with cp, ep, ap:
        from src.tools.customer import get_customers_by_company
        result = await get_customers_by_company("EMEA-01")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T06-09: get_customer_summary_stats returns totals and by_type ─────────────

@pytest.mark.asyncio
async def test_t06_09_get_customer_summary_stats():
    totals = [{"total": 100, "active": 80, "inactive": 20}]
    by_type = [{"customer_type_name": "Enterprise", "count": 60},
               {"customer_type_name": "SMB", "count": 40}]
    cp, ep, ap, em = _patch_exec([totals, by_type])
    with cp, ep, ap:
        from src.tools.customer import get_customer_summary_stats
        result = await get_customer_summary_stats()
    assert result["success"] is True
    assert result["data"]["total"] == 100
    assert result["data"]["active"] == 80
    assert result["data"]["inactive"] == 20
    assert len(result["data"]["by_type"]) == 2


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t06_09_integration_summary_stats(db_conn):
    from src.tools.customer import get_customer_summary_stats
    result = await get_customer_summary_stats()
    assert result["success"] is True
    assert "total" in result["data"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t06_01_integration_search_customers(db_conn):
    from src.tools.customer import search_customers
    result = await search_customers(limit=5)
    assert result["success"] is True
    assert isinstance(result["data"], list)
