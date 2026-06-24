"""
TASK 05 — Reference & Lookup Read Tools
Unit tests: T05-01 through T05-10
"""
import pytest
from unittest.mock import AsyncMock, patch


def _exec_mock(rows):
    return patch("src.tools.reference._exec", new_callable=AsyncMock, return_value=rows)

def _audit_mock():
    return patch("src.tools.reference.log_audit", new_callable=AsyncMock, return_value=True)


# ── T05-01: get_providers status='ACTIVE' returns only ACTIVE rows ────────────

@pytest.mark.asyncio
async def test_t05_01_get_providers_active_only():
    rows = [{"provider_id": 1, "provider_code": "TCL-MAIN",
             "provider_name": "TCL Main", "service_type": "DOMESTIC",
             "country": "US", "status": "ACTIVE"}]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_providers
        result = await get_providers(status="ACTIVE")
    assert result["success"] is True
    assert all(r["status"] == "ACTIVE" for r in result["data"])


# ── T05-02: get_providers status='ALL' returns all ────────────────────────────

@pytest.mark.asyncio
async def test_t05_02_get_providers_all():
    rows = [
        {"provider_code": "TCL-MAIN", "status": "ACTIVE"},
        {"provider_code": "TCL-INT", "status": "INACTIVE"},
    ]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_providers
        result = await get_providers(status="ALL")
    assert result["success"] is True
    assert result["row_count"] == 2


# ── T05-03: get_provider_details valid code returns full record ────────────────

@pytest.mark.asyncio
async def test_t05_03_get_provider_details_found():
    rows = [{"provider_id": 1, "provider_code": "TCL-MAIN",
             "provider_name": "TCL Main", "status": "ACTIVE"}]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_provider_details
        result = await get_provider_details("TCL-MAIN")
    assert result["success"] is True
    assert result["data"]["provider_code"] == "TCL-MAIN"


# ── T05-04: get_provider_details unknown code returns not-found ───────────────

@pytest.mark.asyncio
async def test_t05_04_get_provider_details_not_found():
    with _exec_mock([]), _audit_mock():
        from src.tools.reference import get_provider_details
        result = await get_provider_details("UNKNOWN")
    assert result["success"] is True
    assert result["data"] is None
    assert result["row_count"] == 0


# ── T05-05: get_invoicing_companies country filter works ──────────────────────

@pytest.mark.asyncio
async def test_t05_05_get_invoicing_companies_country_filter():
    rows = [{"company_code": "EMEA-01", "country": "UK", "status": "ACTIVE"}]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_invoicing_companies
        result = await get_invoicing_companies(country="UK")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T05-06: get_currencies returns array (empty is not an error) ──────────────

@pytest.mark.asyncio
async def test_t05_06_get_currencies_empty_ok():
    with _exec_mock([]), _audit_mock():
        from src.tools.reference import get_currencies
        result = await get_currencies()
    assert result["success"] is True
    assert result["data"] == []
    assert result["row_count"] == 0


# ── T05-07: get_currency_by_code('USD') returns CURRENCY_NAME ─────────────────

@pytest.mark.asyncio
async def test_t05_07_get_currency_by_code_usd():
    rows = [{"currency_id": 1, "currency_code": "USD",
             "currency_name": "US Dollar"}]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_currency_by_code
        result = await get_currency_by_code("USD")
    assert result["success"] is True
    assert result["data"]["currency_name"] == "US Dollar"


# ── T05-08: get_currency_by_code('ZZZ') returns not-found ─────────────────────

@pytest.mark.asyncio
async def test_t05_08_get_currency_by_code_not_found():
    with _exec_mock([]), _audit_mock():
        from src.tools.reference import get_currency_by_code
        result = await get_currency_by_code("ZZZ")
    assert result["success"] is True
    assert result["data"] is None
    assert result["row_count"] == 0


# ── T05-09: get_customer_types returns all rows ────────────────────────────────

@pytest.mark.asyncio
async def test_t05_09_get_customer_types():
    rows = [
        {"customer_type_id": 1, "customer_type_code": "ENTERPRISE",
         "customer_type_name": "Enterprise"},
        {"customer_type_id": 2, "customer_type_code": "SMB",
         "customer_type_name": "Small-Medium Business"},
    ]
    with _exec_mock(rows), _audit_mock():
        from src.tools.reference import get_customer_types
        result = await get_customer_types()
    assert result["success"] is True
    assert result["row_count"] == 2


# ── T05-10: All 6 tools write audit log with ACTION_TYPE='READ' ───────────────

@pytest.mark.asyncio
async def test_t05_10_all_tools_audit_read():
    from src.tools.reference import (
        get_providers, get_provider_details, get_invoicing_companies,
        get_currencies, get_currency_by_code, get_customer_types,
    )
    tools_and_args = [
        (get_providers, []),
        (get_provider_details, ["TCL-MAIN"]),
        (get_invoicing_companies, []),
        (get_currencies, []),
        (get_currency_by_code, ["USD"]),
        (get_customer_types, []),
    ]
    for func, args in tools_and_args:
        with _exec_mock([{"dummy": 1}] if "details" in func.__name__ or "code" in func.__name__ else []), \
             patch("src.tools.reference.log_audit", new_callable=AsyncMock) as mock_audit:
            await func(*args)
        assert mock_audit.called, f"{func.__name__} did not call log_audit"
        action_type = mock_audit.call_args[0][3]
        assert action_type == "READ", f"{func.__name__} used action_type={action_type!r}"


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t05_06_integration_get_currencies(db_conn):
    from src.tools.reference import get_currencies
    result = await get_currencies()
    assert result["success"] is True
    # Empty array is valid; just check it doesn't error
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t05_09_integration_get_customer_types(db_conn):
    from src.tools.reference import get_customer_types
    result = await get_customer_types()
    assert result["success"] is True
    assert isinstance(result["data"], list)
