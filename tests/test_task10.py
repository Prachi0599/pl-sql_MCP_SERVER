"""
TASK 10 — Cross-Entity Power Query Tools (Group M)
Unit tests: T10-01 through T10-10
"""
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch


# ── mock helpers ──────────────────────────────────────────────────────────────

def _make_conn():
    conn = MagicMock()
    conn.close = AsyncMock()
    return conn


def _stack(exec_rows, resolvers: dict | None = None):
    s = ExitStack()
    conn = _make_conn()
    s.enter_context(
        patch("src.tools.power.get_connection",
              new_callable=AsyncMock, return_value=conn))
    s.enter_context(
        patch("src.tools.power._exec",
              new_callable=AsyncMock, side_effect=exec_rows))
    s.enter_context(
        patch("src.tools.power.log_audit",
              new_callable=AsyncMock, return_value=True))
    for fname, retval in (resolvers or {}).items():
        if retval is None:
            s.enter_context(
                patch(f"src.tools.power.{fname}",
                      new_callable=AsyncMock,
                      side_effect=ValueError("Not found")))
        else:
            s.enter_context(
                patch(f"src.tools.power.{fname}",
                      new_callable=AsyncMock, return_value=retval))
    return s, conn


# ── T10-01: search_globally hits CUSTOMER_NAME, ACCOUNT_NUMBER, EMAIL, INVOICE ─

@pytest.mark.asyncio
async def test_t10_01_search_globally_multi_entity():
    rows = [
        {"entity_type": "CUSTOMER", "entity_id": "1",
         "entity_number": "CUST-001", "name": "Acme Corp", "detail": "ACTIVE"},
        {"entity_type": "ACCOUNT", "entity_id": "10",
         "entity_number": "ACC-001", "name": "Main Account", "detail": "ACTIVE"},
        {"entity_type": "CONTACT", "entity_id": "5",
         "entity_number": "acme@corp.com", "name": "Jane Doe",
         "detail": "CFO"},
        {"entity_type": "INVOICE", "entity_id": "99",
         "entity_number": "INV-ACME-001", "name": "UNPAID",
         "detail": "1200.0"},
    ]
    with _stack([rows])[0]:
        from src.tools.power import search_globally
        result = await search_globally("acme")
    assert result["success"] is True
    assert result["row_count"] == 4
    types = {r["entity_type"] for r in result["data"]}
    assert "CUSTOMER" in types
    assert "ACCOUNT" in types
    assert "CONTACT" in types
    assert "INVOICE" in types


# ── T10-02: search_globally results include entity_type label ────────────────

@pytest.mark.asyncio
async def test_t10_02_search_globally_has_entity_type():
    rows = [{"entity_type": "CUSTOMER", "entity_id": "1",
             "entity_number": "CUST-001", "name": "Foo Corp", "detail": "ACTIVE"}]
    with _stack([rows])[0]:
        from src.tools.power import search_globally
        result = await search_globally("Foo")
    assert result["success"] is True
    assert "entity_type" in result["data"][0]
    assert result["data"][0]["entity_type"] == "CUSTOMER"


# ── T10-03: get_customer_health_check flags missing_address ──────────────────

@pytest.mark.asyncio
async def test_t10_03_health_check_missing_address():
    counts = [{"address_count": 0, "contact_count": 1,
               "active_product_count": 2, "unpaid_bill_count": 0,
               "unpaid_amount": 0, "events_this_month": 5}]
    with _stack([counts], {"resolve_customer_number": 1})[0]:
        from src.tools.power import get_customer_health_check
        result = await get_customer_health_check("CUST-001")
    assert result["success"] is True
    assert result["data"]["missing_address"] is True
    assert result["data"]["missing_contact"] is False
    assert result["data"]["no_active_products"] is False


# ── T10-04: get_customer_health_check flags no_active_products ───────────────

@pytest.mark.asyncio
async def test_t10_04_health_check_no_active_products():
    counts = [{"address_count": 1, "contact_count": 1,
               "active_product_count": 0, "unpaid_bill_count": 0,
               "unpaid_amount": 0, "events_this_month": 3}]
    with _stack([counts], {"resolve_customer_number": 1})[0]:
        from src.tools.power import get_customer_health_check
        result = await get_customer_health_check("CUST-001")
    assert result["success"] is True
    assert result["data"]["no_active_products"] is True
    assert result["data"]["missing_address"] is False


# ── T10-05: get_customer_health_check flags unpaid_bills ─────────────────────

@pytest.mark.asyncio
async def test_t10_05_health_check_unpaid_bills():
    counts = [{"address_count": 1, "contact_count": 1,
               "active_product_count": 2, "unpaid_bill_count": 3,
               "unpaid_amount": 5000.0, "events_this_month": 10}]
    with _stack([counts], {"resolve_customer_number": 1})[0]:
        from src.tools.power import get_customer_health_check
        result = await get_customer_health_check("CUST-001")
    assert result["success"] is True
    assert result["data"]["has_unpaid_bills"] is True
    assert result["data"]["unpaid_bill_count"] == 3
    assert result["data"]["unpaid_amount"] == 5000.0


# ── T10-06: get_customer_health_check flags no_events_this_month ─────────────

@pytest.mark.asyncio
async def test_t10_06_health_check_no_events_this_month():
    counts = [{"address_count": 2, "contact_count": 1,
               "active_product_count": 1, "unpaid_bill_count": 0,
               "unpaid_amount": 0, "events_this_month": 0}]
    with _stack([counts], {"resolve_customer_number": 1})[0]:
        from src.tools.power import get_customer_health_check
        result = await get_customer_health_check("CUST-001")
    assert result["success"] is True
    assert result["data"]["no_events_this_month"] is True
    assert result["data"]["raw_counts"]["events_this_month"] == 0


# ── T10-07: get_inactive_entities returns INACTIVE customers + accounts ────────

@pytest.mark.asyncio
async def test_t10_07_get_inactive_entities_all():
    rows = [
        {"entity_type": "ACCOUNT", "entity_number": "ACC-900",
         "entity_name": "Old Account", "status": "INACTIVE",
         "relevant_date": None},
        {"entity_type": "CUSTOMER", "entity_number": "CUST-900",
         "entity_name": "Old Corp", "status": "INACTIVE",
         "relevant_date": "2020-01-01"},
    ]
    with _stack([rows])[0]:
        from src.tools.power import get_inactive_entities
        result = await get_inactive_entities()
    assert result["success"] is True
    types = {r["entity_type"] for r in result["data"]}
    assert "CUSTOMER" in types
    assert "ACCOUNT" in types
    assert all(r["status"] == "INACTIVE" for r in result["data"])


# ── T10-08: get_expiring_products(30) returns correct date window ─────────────

@pytest.mark.asyncio
async def test_t10_08_get_expiring_products_date_window():
    rows = [
        {"cust_product_id": 1, "end_date": "2026-07-10",
         "days_until_expiry": 17, "product_code": "MPLS-STD",
         "product_name": "MPLS Standard", "product_type": "DATA",
         "customer_number": "CUST-001", "customer_name": "Acme Corp",
         "account_number": "ACC-001"},
    ]
    with _stack([rows])[0]:
        from src.tools.power import get_expiring_products
        result = await get_expiring_products(days_ahead=30)
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["days_until_expiry"] <= 30
    assert result["data"][0]["product_code"] == "MPLS-STD"


# ── T10-09: get_full_hierarchy returns nested JSON with accounts + products ───

@pytest.mark.asyncio
async def test_t10_09_get_full_hierarchy_structure():
    cust_row = [{"customer_id": 1, "customer_number": "CUST-001",
                 "customer_name": "Acme Corp", "status": "ACTIVE",
                 "start_date": "2023-01-01", "company_code": "EMEA-01",
                 "company_name": "EMEA Corp", "customer_type_name": "Enterprise"}]
    acc_rows = [{"account_id": 10, "account_number": "ACC-001",
                 "account_name": "Main", "status": "ACTIVE",
                 "billing_cycle": "MONTHLY", "currency_code": "USD",
                 "billable_flag": "Y", "commissioning_date": "2023-06-01",
                 "termination_date": None}]
    prod_rows = [{"account_id": 10, "product_code": "MPLS-STD",
                  "product_name": "MPLS", "product_type": "DATA",
                  "status": "ACTIVE", "start_date": "2023-06-01",
                  "end_date": None}]
    with _stack([cust_row, acc_rows, prod_rows])[0]:
        from src.tools.power import get_full_hierarchy
        result = await get_full_hierarchy("CUST-001")
    assert result["success"] is True
    h = result["data"]
    assert "company" in h
    assert "customer" in h
    assert "accounts" in h
    assert h["company"]["company_code"] == "EMEA-01"
    assert h["customer"]["customer_name"] == "Acme Corp"
    assert len(h["accounts"]) == 1
    assert h["accounts"][0]["account_number"] == "ACC-001"
    assert len(h["accounts"][0]["products"]) == 1
    assert h["accounts"][0]["products"][0]["product_code"] == "MPLS-STD"


# ── T10-10: get_accounts_no_events returns active accounts with no events ──────

@pytest.mark.asyncio
async def test_t10_10_get_accounts_no_events():
    rows = [
        {"account_number": "ACC-500", "account_name": "Silent Account",
         "status": "ACTIVE", "billing_cycle": "MONTHLY",
         "customer_number": "CUST-050", "customer_name": "Quiet Corp",
         "commissioning_date": "2024-01-01"},
    ]
    with _stack([rows])[0]:
        from src.tools.power import get_accounts_no_events
        result = await get_accounts_no_events()
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["account_number"] == "ACC-500"


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_01_integration_search_globally(db_conn):
    from src.tools.power import search_globally
    result = await search_globally("A", limit=10)
    assert result["success"] is True
    assert isinstance(result["data"], list)
    if result["data"]:
        assert "entity_type" in result["data"][0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_03_integration_health_check(db_conn):
    from src.tools.customer import search_customers
    from src.tools.power import get_customer_health_check
    custs = await search_customers(limit=1)
    if not custs["data"]:
        pytest.skip("No customers")
    result = await get_customer_health_check(custs["data"][0]["customer_number"])
    assert result["success"] is True
    d = result["data"]
    assert "missing_address" in d
    assert "no_active_products" in d
    assert "has_unpaid_bills" in d
    assert "no_events_this_month" in d


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_07_integration_inactive_entities(db_conn):
    from src.tools.power import get_inactive_entities
    result = await get_inactive_entities()
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_08_integration_expiring_products(db_conn):
    from src.tools.power import get_expiring_products
    result = await get_expiring_products(days_ahead=365)
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_09_integration_full_hierarchy(db_conn):
    from src.tools.customer import search_customers
    from src.tools.power import get_full_hierarchy
    custs = await search_customers(limit=1)
    if not custs["data"]:
        pytest.skip("No customers")
    result = await get_full_hierarchy(custs["data"][0]["customer_number"])
    assert result["success"] is True
    if result["data"]:
        assert "accounts" in result["data"]
        assert "company" in result["data"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t10_10_integration_accounts_no_events(db_conn):
    from src.tools.power import get_accounts_no_events
    result = await get_accounts_no_events(limit=10)
    assert result["success"] is True
    assert isinstance(result["data"], list)
