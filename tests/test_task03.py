"""
TASK 03 — ID Resolver Helpers
Unit tests: T03-01 through T03-10
"""
import pytest
from unittest.mock import MagicMock, AsyncMock


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_conn(return_row):
    """Build a mock AsyncConnection whose cursor.fetchone returns *return_row*."""
    mock_cur = MagicMock()
    mock_cur.execute = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value=return_row)
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


# ── T03-01: resolveCustomerNumber returns correct CUSTOMER_ID ─────────────────

@pytest.mark.asyncio
async def test_t03_01_resolve_customer_number_found():
    from src.db.resolvers import resolve_customer_number
    conn, _ = _mock_conn((101,))
    result = await resolve_customer_number(conn, "CUST-001")
    assert result == 101


# ── T03-02: resolveCustomerNumber('NONEXISTENT') throws human-readable error ──

@pytest.mark.asyncio
async def test_t03_02_resolve_customer_number_not_found():
    from src.db.resolvers import resolve_customer_number
    conn, _ = _mock_conn(None)
    with pytest.raises(ValueError, match="NONEXISTENT"):
        await resolve_customer_number(conn, "NONEXISTENT")


# ── T03-03: resolveCompanyCode returns correct INV_COMPANY_ID ─────────────────

@pytest.mark.asyncio
async def test_t03_03_resolve_company_code():
    from src.db.resolvers import resolve_company_code
    conn, _ = _mock_conn((5,))
    result = await resolve_company_code(conn, "EMEA-01")
    assert result == 5


# ── T03-04: resolveCurrencyCode returns correct CURRENCY_ID ───────────────────

@pytest.mark.asyncio
async def test_t03_04_resolve_currency_code():
    from src.db.resolvers import resolve_currency_code
    conn, _ = _mock_conn((3,))
    result = await resolve_currency_code(conn, "USD")
    assert result == 3


# ── T03-05: resolveAccountNumber returns correct ACCOUNT_ID ───────────────────

@pytest.mark.asyncio
async def test_t03_05_resolve_account_number():
    from src.db.resolvers import resolve_account_number
    conn, _ = _mock_conn((42,))
    result = await resolve_account_number(conn, "ACC-8821")
    assert result == 42


# ── T03-06: resolveProductCode returns correct PRODUCT_ID ─────────────────────

@pytest.mark.asyncio
async def test_t03_06_resolve_product_code():
    from src.db.resolvers import resolve_product_code
    conn, _ = _mock_conn((7,))
    result = await resolve_product_code(conn, "PROD-MPLS")
    assert result == 7


# ── T03-07: resolveProviderCode returns correct PROVIDER_ID ───────────────────

@pytest.mark.asyncio
async def test_t03_07_resolve_provider_code():
    from src.db.resolvers import resolve_provider_code
    conn, _ = _mock_conn((2,))
    result = await resolve_provider_code(conn, "TCL-MAIN")
    assert result == 2


# ── T03-08: resolveCustomerTypeCode returns correct CUSTOMER_TYPE_ID ──────────

@pytest.mark.asyncio
async def test_t03_08_resolve_customer_type_code():
    from src.db.resolvers import resolve_customer_type_code
    conn, _ = _mock_conn((1,))
    result = await resolve_customer_type_code(conn, "ENTERPRISE")
    assert result == 1


# ── T03-09: All resolvers are case-insensitive ────────────────────────────────

@pytest.mark.asyncio
async def test_t03_09_case_insensitive_currency():
    from src.db.resolvers import resolve_currency_code
    conn_lower, cur_lower = _mock_conn((3,))
    conn_upper, cur_upper = _mock_conn((3,))

    result_lower = await resolve_currency_code(conn_lower, "usd")
    result_upper = await resolve_currency_code(conn_upper, "USD")

    assert result_lower == result_upper == 3

    # Verify the SQL used UPPER() on the bind variable side
    call_args_lower = cur_lower.execute.call_args[0]
    sql = call_args_lower[0]
    assert "UPPER(:1)" in sql


@pytest.mark.asyncio
async def test_t03_09_case_insensitive_customer():
    from src.db.resolvers import resolve_customer_number
    conn, cur = _mock_conn((55,))
    await resolve_customer_number(conn, "cust-001")
    sql = cur.execute.call_args[0][0]
    assert "UPPER(:1)" in sql
    assert "UPPER(CUSTOMER_NUMBER)" in sql


# ── T03-10: Error message includes the invalid value ─────────────────────────

@pytest.mark.asyncio
async def test_t03_10_error_includes_invalid_value():
    from src.db.resolvers import resolve_customer_number
    conn, _ = _mock_conn(None)
    with pytest.raises(ValueError) as exc_info:
        await resolve_customer_number(conn, "CUST-INVALID-999")
    assert "CUST-INVALID-999" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t03_10_error_includes_value_for_account():
    from src.db.resolvers import resolve_account_number
    conn, _ = _mock_conn(None)
    with pytest.raises(ValueError) as exc_info:
        await resolve_account_number(conn, "ACC-GHOST")
    assert "ACC-GHOST" in str(exc_info.value)


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t03_01_integration_resolve_customer(db_conn):
    from src.db.resolvers import resolve_customer_number
    # Insert a test customer and resolve it
    with db_conn.cursor() as cur:
        await cur.execute(
            "SELECT CUSTOMER_NUMBER FROM MCP_APP.CUSTOMER WHERE ROWNUM = 1"
        )
        row = await cur.fetchone()
    if row is None:
        pytest.skip("No customers in DB")
    customer_number = row[0]
    result = await resolve_customer_number(db_conn, customer_number)
    assert isinstance(result, int) and result > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t03_04_integration_resolve_currency(db_conn):
    from src.db.resolvers import resolve_currency_code
    with db_conn.cursor() as cur:
        await cur.execute(
            "SELECT CURRENCY_CODE FROM MCP_APP.CURRENCY WHERE ROWNUM = 1"
        )
        row = await cur.fetchone()
    if row is None:
        pytest.skip("No currencies in DB")
    code = row[0]
    result = await resolve_currency_code(db_conn, code)
    assert isinstance(result, int) and result > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t03_09_integration_case_insensitive(db_conn):
    from src.db.resolvers import resolve_currency_code
    with db_conn.cursor() as cur:
        await cur.execute(
            "SELECT CURRENCY_CODE FROM MCP_APP.CURRENCY WHERE ROWNUM = 1"
        )
        row = await cur.fetchone()
    if row is None:
        pytest.skip("No currencies in DB")
    code = row[0]
    id_upper = await resolve_currency_code(db_conn, code.upper())
    id_lower = await resolve_currency_code(db_conn, code.lower())
    assert id_upper == id_lower
