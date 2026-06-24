"""
TASK 13 — Error Handling, Pagination & Security
Unit tests: T13-01 through T13-11
"""
import asyncio
import json
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import oracledb


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn():
    c = MagicMock()
    c.close = AsyncMock()
    c.commit = AsyncMock()
    return c


def _make_ora_error(code: int, message: str = "") -> oracledb.DatabaseError:
    """Create a real oracledb.DatabaseError subclass with a controllable error code."""
    class _FakeOra(oracledb.DatabaseError):
        pass

    exc = _FakeOra.__new__(_FakeOra)
    exc.args = (SimpleNamespace(
        code=code,
        message=message or f"ORA-{code:05d}: oracle error",
    ),)
    return exc


# ── T13-01: ORA-00001 → "Duplicate value already exists" ─────────────────────

def test_t13_01_ora_00001_duplicate_value():
    from src.utils.errors import map_oracle_error
    exc = _make_ora_error(1, "ORA-00001: unique constraint (MCP_APP.CURRENCY_UQ) violated")
    result = map_oracle_error(exc)
    assert result["success"] is False
    assert result["error_code"] == "ORA-00001"
    assert result["message"] == "Duplicate value already exists"


# ── T13-02: ORA-02291 → "Referenced entity does not exist" ───────────────────

def test_t13_02_ora_02291_fk_violation():
    from src.utils.errors import map_oracle_error
    exc = _make_ora_error(2291, "ORA-02291: integrity constraint violated - parent key not found")
    result = map_oracle_error(exc)
    assert result["success"] is False
    assert result["error_code"] == "ORA-02291"
    assert result["message"] == "Referenced entity does not exist"


# ── T13-03: ORA-01400 → "Required field cannot be empty" ─────────────────────

def test_t13_03_ora_01400_not_null():
    from src.utils.errors import map_oracle_error
    exc = _make_ora_error(1400, "ORA-01400: cannot insert NULL into (MCP_APP.CUSTOMER.CUSTOMER_NAME)")
    result = map_oracle_error(exc)
    assert result["success"] is False
    assert result["error_code"] == "ORA-01400"
    assert result["message"] == "Required field cannot be empty"


# ── T13-04: ORA-01403 → "No data found" ──────────────────────────────────────

def test_t13_04_ora_01403_no_data_found():
    from src.utils.errors import map_oracle_error
    exc = _make_ora_error(1403, "ORA-01403: no data found")
    result = map_oracle_error(exc)
    assert result["success"] is False
    assert result["error_code"] == "ORA-01403"
    assert result["message"] == "No data found"


# ── T13-05: SQL injection safely bound — no rows, no error ───────────────────

@pytest.mark.asyncio
async def test_t13_05_sql_injection_passed_as_bind_param():
    """Verify the injection string is a bind param, NOT embedded in SQL."""
    captured_params = []

    async def mock_exec(conn, sql, params=None):
        captured_params.extend(params or [])
        # Verify the SQL itself is clean — no DROP TABLE in it
        assert "DROP TABLE" not in sql.upper()
        return []

    injection = "'; DROP TABLE CUSTOMER; --"
    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", mock_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers(name=injection)

    assert result["success"] is True
    assert result["data"] == []
    # Injection string must appear in bind params, not interpolated in SQL
    assert injection in captured_params


# ── T13-06: limit=5 returns exactly 5 rows ────────────────────────────────────

@pytest.mark.asyncio
async def test_t13_06_limit_5_returns_5_rows():
    five_rows = [{"customer_id": i, "customer_number": f"CUST-{i:06d}",
                  "customer_name": f"Customer {i}", "status": "ACTIVE",
                  "customer_type_name": "Enterprise", "company_code": "EMEA",
                  "start_date": "2024-01-01"}
                 for i in range(1, 6)]

    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec",
               new_callable=AsyncMock, return_value=five_rows), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers(limit=5)

    assert result["success"] is True
    assert result["row_count"] == 5
    assert len(result["data"]) == 5


# ── T13-07: limit=5 offset=5 returns next page ───────────────────────────────

@pytest.mark.asyncio
async def test_t13_07_offset_5_returns_next_page():
    """Rows 6-10 should come back when offset=5."""
    rows_page2 = [{"customer_id": i, "customer_number": f"CUST-{i:06d}",
                   "customer_name": f"Customer {i}", "status": "ACTIVE",
                   "customer_type_name": "Enterprise", "company_code": "EMEA",
                   "start_date": "2024-01-01"}
                  for i in range(6, 11)]

    captured_sql = []
    captured_params = []

    async def mock_exec(conn, sql, params=None):
        captured_sql.append(sql)
        captured_params.append(list(params or []))
        return rows_page2

    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", mock_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers(limit=5, offset=5)

    assert result["success"] is True
    assert result["row_count"] == 5
    # Verify offset=5 was in the params passed to _exec
    flat_params = captured_params[0]
    assert 5 in flat_params  # offset value
    assert 5 in flat_params  # limit value (both are 5 here)
    # Verify the SQL contains OFFSET ... ROWS FETCH NEXT
    assert "OFFSET" in captured_sql[0].upper()
    assert "FETCH NEXT" in captured_sql[0].upper()


# ── T13-08: limit=501 capped to 500 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_t13_08_limit_501_capped_to_500():
    from src.tools.customer import _clamp
    assert _clamp(501) == 500
    assert _clamp(0) == 1
    assert _clamp(-10) == 1
    assert _clamp(500) == 500
    assert _clamp(499) == 499


@pytest.mark.asyncio
async def test_t13_08b_capped_limit_reflected_in_params():
    """The SQL params should contain 500, not 501."""
    captured_params = []

    async def mock_exec(conn, sql, params=None):
        captured_params.extend(params or [])
        return []

    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", mock_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        await search_customers(limit=501)

    assert 501 not in captured_params
    assert 500 in captured_params


# ── T13-09: DB failure → structured error, server stays up ───────────────────

@pytest.mark.asyncio
async def test_t13_09_db_failure_returns_structured_error():
    """Oracle error during a DB call returns structured dict — no exception propagates."""
    exc = _make_ora_error(4043, "ORA-04043: object does not exist")

    async def exploding_exec(*args, **kwargs):
        raise exc

    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", exploding_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers()

    # Server stayed up — result is a dict, not a raised exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "error_code" in result
    assert result["error_code"].startswith("ORA-")


@pytest.mark.asyncio
async def test_t13_09b_non_oracle_error_also_structured():
    """Non-Oracle exceptions also return structured dict."""
    async def exploding_exec(*args, **kwargs):
        raise RuntimeError("Connection pool exhausted")

    with patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", exploding_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers()

    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["error_code"] == "INTERNAL_ERROR"


# ── T13-10: Query > timeout cancelled with message ───────────────────────────

@pytest.mark.asyncio
async def test_t13_10_slow_query_returns_timeout_error():
    """Simulate a query that exceeds _QUERY_TIMEOUT — returns TIMEOUT error."""

    async def slow_exec(conn, sql, params=None):
        await asyncio.sleep(10)   # long-running; will be cancelled by wait_for
        return []

    # Patch timeout to 0.05s so the test runs fast
    with patch("src.tools.customer._QUERY_TIMEOUT", 0.05), \
         patch("src.tools.customer.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.customer._exec", slow_exec), \
         patch("src.tools.customer.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.customer import search_customers
        result = await search_customers()

    assert result["success"] is False
    assert result["error_code"] == "TIMEOUT"
    assert "timed out" in result["message"].lower()


# ── T13-11: Empty required field fails before any DB call ────────────────────

@pytest.mark.asyncio
async def test_t13_11_empty_field_fails_before_db_call():
    """Validation must fire before get_connection() is awaited."""
    db_mock = AsyncMock()
    with patch("src.tools.writes.get_connection", db_mock):
        from src.tools.writes import create_currency
        result = await create_currency("", "Empty Code Test")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    db_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_t13_11b_whitespace_only_field_also_fails():
    db_mock = AsyncMock()
    with patch("src.tools.writes.get_connection", db_mock):
        from src.tools.writes import create_currency
        result = await create_currency("   ", "Whitespace Code")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    db_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_t13_11c_multiple_validators_checked():
    """Verify several write tools catch empty required fields before DB."""
    db_mock = AsyncMock()
    with patch("src.tools.writes.get_connection", db_mock):
        from src.tools.writes import (
            add_customer_address, create_billing_adjustment,
            create_provider,
        )
        r1 = await add_customer_address("CUST-001", "BILLING", "1 St", "", "UK")
        r2 = await create_billing_adjustment("INV-1", "ACC-1", "CR", -5.0, "bad")
        r3 = await create_provider("", "Name", "DATA", "UK")

    assert all(r["error_code"] == "VALIDATION_ERROR" for r in [r1, r2, r3])
    db_mock.assert_not_awaited()


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t13_05_integration_sql_injection_no_error(db_conn):
    from src.tools.customer import search_customers
    result = await search_customers(name="'; DROP TABLE CUSTOMER; --")
    assert result["success"] is True
    assert result["data"] == []   # no matches and NO error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t13_06_integration_limit_5(db_conn):
    from src.tools.customer import search_customers
    result = await search_customers(limit=5)
    assert result["success"] is True
    assert result["row_count"] <= 5
    assert len(result["data"]) <= 5


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t13_07_integration_offset_returns_different_data(db_conn):
    from src.tools.customer import search_customers
    page1 = await search_customers(limit=5, offset=0)
    page2 = await search_customers(limit=5, offset=5)
    assert page1["success"] is True
    assert page2["success"] is True
    # If there are >= 6 customers, pages should differ
    if page1["row_count"] == 5 and page2["row_count"] > 0:
        ids1 = {r["customer_number"] for r in page1["data"]}
        ids2 = {r["customer_number"] for r in page2["data"]}
        assert ids1.isdisjoint(ids2), "Pages must not overlap"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t13_08_integration_limit_501_capped(db_conn):
    from src.tools.customer import search_customers
    result = await search_customers(limit=501)
    assert result["success"] is True
    assert result["row_count"] <= 500


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t13_01_integration_duplicate_currency_is_noop(db_conn):
    """A duplicate currency code is caught up-front by no-op detection and never
    staged — so no doomed approval request is created.

    (The ORA-00001 unique-constraint mapping on dispatch is still covered by the
    unit test test_t12_13b_create_currency_approval_maps_ora_00001.)"""
    from src.tools.writes import create_currency
    from src.tools.approval import _exec
    from src.db.pool import get_connection
    c = await get_connection()
    try:
        rows = await _exec(c, "SELECT CURRENCY_CODE FROM MCP_APP.CURRENCY FETCH FIRST 1 ROW ONLY")
    finally:
        await c.close()

    if not rows:
        pytest.skip("No existing currency to test duplicate")

    existing_code = rows[0]["currency_code"]
    req = await create_currency(existing_code, "Duplicate Test")
    assert req["success"] is True
    assert req["status"] == "NO_CHANGE"
    assert req.get("no_change") is True
    assert req.get("request_id") is None
