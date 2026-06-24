"""
TASK 07 — Address, Contact, Account Read Tools (Groups C & D read)
Unit tests: T07-01 through T07-10
"""
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch


# ── mock helpers ──────────────────────────────────────────────────────────────

def _make_conn_mock():
    conn = MagicMock()
    conn.close = AsyncMock()
    return conn


def _stack(exec_rows, resolvers: dict | None = None):
    """
    Return an ExitStack with patched:
      get_connection, _exec (side_effect list), log_audit,
      and any resolver functions in *resolvers* {fn_name: return_value | None=ValueError}.
    """
    stack = ExitStack()
    conn = _make_conn_mock()
    stack.enter_context(
        patch("src.tools.account.get_connection",
              new_callable=AsyncMock, return_value=conn))
    stack.enter_context(
        patch("src.tools.account._exec",
              new_callable=AsyncMock, side_effect=exec_rows))
    stack.enter_context(
        patch("src.tools.account.log_audit",
              new_callable=AsyncMock, return_value=True))
    for fname, retval in (resolvers or {}).items():
        if retval is None:
            stack.enter_context(
                patch(f"src.tools.account.{fname}",
                      new_callable=AsyncMock,
                      side_effect=ValueError("Not found")))
        else:
            stack.enter_context(
                patch(f"src.tools.account.{fname}",
                      new_callable=AsyncMock, return_value=retval))
    return stack, conn


# ── T07-01: get_customer_addresses returns all ADDRESS fields ─────────────────

@pytest.mark.asyncio
async def test_t07_01_get_customer_addresses_fields():
    addr_rows = [
        {"address_id": 1, "address_type": "BILLING", "address_line1": "1 Main St",
         "city": "London", "state": None, "country": "UK", "postal_code": "EC1A"},
    ]
    with _stack([addr_rows], {"resolve_customer_number": 42})[0]:
        from src.tools.account import get_customer_addresses
        result = await get_customer_addresses("CUST-001")
    assert result["success"] is True
    assert result["row_count"] == 1
    row = result["data"][0]
    assert row["address_type"] == "BILLING"
    assert row["city"] == "London"


# ── T07-02: get_customer_addresses no address → empty list, not error ─────────

@pytest.mark.asyncio
async def test_t07_02_get_customer_addresses_empty():
    with _stack([[]], {"resolve_customer_number": 42})[0]:
        from src.tools.account import get_customer_addresses
        result = await get_customer_addresses("CUST-001")
    assert result["success"] is True
    assert result["data"] == []
    assert result["row_count"] == 0


# ── T07-03: get_customer_contacts returns CONTACT joined with CONTACT_DETAILS ─

@pytest.mark.asyncio
async def test_t07_03_get_customer_contacts_joined():
    con_rows = [
        {"contact_id": 1, "contact_name": "Jane Doe", "designation": "CFO",
         "email": "jane@acme.com", "phone_number": "+44-20-1234",
         "alternate_email": None},
    ]
    with _stack([con_rows], {"resolve_customer_number": 42})[0]:
        from src.tools.account import get_customer_contacts
        result = await get_customer_contacts("CUST-001")
    assert result["success"] is True
    row = result["data"][0]
    assert row["contact_name"] == "Jane Doe"
    assert row["phone_number"] == "+44-20-1234"
    assert "alternate_email" in row


# ── T07-04: search_contacts_by_email returns matching contacts ────────────────

@pytest.mark.asyncio
async def test_t07_04_search_contacts_by_email():
    rows = [
        {"contact_id": 1, "contact_name": "Jane Doe", "email": "jane@acme.com",
         "designation": "CFO", "phone_number": "+44",
         "customer_number": "CUST-001", "customer_name": "Acme Corp"},
    ]
    with _stack([rows])[0]:
        from src.tools.account import search_contacts_by_email
        result = await search_contacts_by_email("acme.com")
    assert result["success"] is True
    assert result["row_count"] == 1
    assert "acme.com" in result["data"][0]["email"]


# ── T07-05: get_accounts_by_customer returns ACCOUNT + ACCOUNT_DETAILS + CUR ─

@pytest.mark.asyncio
async def test_t07_05_get_accounts_by_customer_full():
    acc_rows = [
        {"account_id": 1, "account_number": "ACC-001", "account_name": "Main",
         "status": "ACTIVE", "billing_cycle": "MONTHLY", "currency_code": "USD",
         "billable_flag": "Y", "commissioning_date": "2024-01-01",
         "termination_date": None},
    ]
    with _stack([acc_rows], {"resolve_customer_number": 42})[0]:
        from src.tools.account import get_accounts_by_customer
        result = await get_accounts_by_customer("CUST-001")
    assert result["success"] is True
    row = result["data"][0]
    assert row["currency_code"] == "USD"
    assert row["billable_flag"] == "Y"
    assert row["termination_date"] is None


# ── T07-06: get_accounts_by_customer status='ACTIVE' filters correctly ─────────

@pytest.mark.asyncio
async def test_t07_06_get_accounts_by_customer_status_filter():
    rows = [{"account_id": 1, "account_number": "ACC-001", "status": "ACTIVE",
             "billing_cycle": "MONTHLY", "currency_code": "USD",
             "billable_flag": "Y", "commissioning_date": None,
             "termination_date": None, "account_name": "Main"}]
    with _stack([rows], {"resolve_customer_number": 42})[0]:
        from src.tools.account import get_accounts_by_customer
        result = await get_accounts_by_customer("CUST-001", status="ACTIVE")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T07-07: get_account_details falls back to direct SQL on package error ─────

@pytest.mark.asyncio
async def test_t07_07_get_account_details_fallback():
    acc_rows = [
        {"account_id": 1, "account_number": "ACC-001", "account_name": "Main",
         "status": "ACTIVE", "billing_cycle": "MONTHLY", "currency_code": "USD",
         "billable_flag": "Y", "commissioning_date": "2024-01-01",
         "termination_date": None, "customer_number": "CUST-001"},
    ]
    conn_mock = _make_conn_mock()
    # callfunc raises → fallback SQL runs
    cur_mock = MagicMock()
    cur_mock.callfunc = AsyncMock(side_effect=Exception("package unavailable"))
    cur_mock.__enter__ = MagicMock(return_value=cur_mock)
    cur_mock.__exit__ = MagicMock(return_value=None)
    conn_mock.cursor.return_value = cur_mock

    with patch("src.tools.account.get_connection",
               new_callable=AsyncMock, return_value=conn_mock), \
         patch("src.tools.account.resolve_account_number",
               new_callable=AsyncMock, return_value=1), \
         patch("src.tools.account._exec",
               new_callable=AsyncMock, return_value=acc_rows), \
         patch("src.tools.account.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.account import get_account_details
        result = await get_account_details("ACC-001")

    assert result["success"] is True
    assert result["data"]["account_number"] == "ACC-001"


# ── T07-08: get_account_commissioning_info null TERMINATION_DATE is None ──────

@pytest.mark.asyncio
async def test_t07_08_commissioning_info_null_termination():
    rows = [
        {"account_number": "ACC-001", "status": "ACTIVE",
         "billing_cycle": "MONTHLY", "billable_flag": "Y",
         "commissioning_date": "2024-01-01", "termination_date": None},
    ]
    with _stack([rows], {"resolve_account_number": 1})[0]:
        from src.tools.account import get_account_commissioning_info
        result = await get_account_commissioning_info("ACC-001")
    assert result["success"] is True
    assert result["data"]["termination_date"] is None


# ── T07-09: get_accounts_by_billing_cycle('MONTHLY') filters correctly ─────────

@pytest.mark.asyncio
async def test_t07_09_accounts_by_billing_cycle_monthly():
    rows = [
        {"account_id": 1, "account_number": "ACC-001",
         "account_name": "Main", "status": "ACTIVE",
         "billing_cycle": "MONTHLY", "currency_code": "USD",
         "customer_number": "CUST-001"},
    ]
    with _stack([rows])[0]:
        from src.tools.account import get_accounts_by_billing_cycle
        result = await get_accounts_by_billing_cycle("MONTHLY")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T07-10: get_accounts_pending_termination(30) returns correct date range ───

@pytest.mark.asyncio
async def test_t07_10_accounts_pending_termination():
    rows = [
        {"account_number": "ACC-999", "account_name": "Closing",
         "status": "ACTIVE", "billing_cycle": "MONTHLY",
         "customer_number": "CUST-099", "customer_name": "Acme",
         "termination_date": "2026-07-20", "days_until_termination": 27},
    ]
    with _stack([rows])[0]:
        from src.tools.account import get_accounts_pending_termination
        result = await get_accounts_pending_termination(30)
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["days_until_termination"] == 27


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t07_01_integration_get_addresses(db_conn):
    from src.tools.customer import search_customers
    from src.tools.account import get_customer_addresses
    cust = await search_customers(limit=1)
    if not cust["data"]:
        pytest.skip("No customers in DB")
    result = await get_customer_addresses(cust["data"][0]["customer_number"])
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t07_03_integration_get_contacts(db_conn):
    from src.tools.customer import search_customers
    from src.tools.account import get_customer_contacts
    cust = await search_customers(limit=1)
    if not cust["data"]:
        pytest.skip("No customers in DB")
    result = await get_customer_contacts(cust["data"][0]["customer_number"])
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t07_05_integration_accounts_by_customer(db_conn):
    from src.tools.customer import search_customers
    from src.tools.account import get_accounts_by_customer
    cust = await search_customers(limit=1)
    if not cust["data"]:
        pytest.skip("No customers in DB")
    result = await get_accounts_by_customer(cust["data"][0]["customer_number"])
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t07_09_integration_accounts_by_billing_cycle(db_conn):
    from src.tools.account import get_accounts_by_billing_cycle
    result = await get_accounts_by_billing_cycle("MONTHLY", status="ALL")
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t07_10_integration_accounts_pending_termination(db_conn):
    from src.tools.account import get_accounts_pending_termination
    result = await get_accounts_pending_termination(365)
    assert result["success"] is True
    assert isinstance(result["data"], list)
