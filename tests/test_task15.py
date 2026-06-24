"""
TASK 15 — customer_read_agent + billing_read_agent
Unit tests: T15-01 through T15-10

All unit tests mock the OpenAI client so no real API calls are made.
Integration tests hit both the real Oracle DB and the real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_CUST_MODULE = "src.agents.customer_read_agent"
_BILL_MODULE = "src.agents.billing_read_agent"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _tool_call(name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = f"call_{name}"
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_response(*tool_calls) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = list(tool_calls)
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(module: str, response: MagicMock):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    return patch(f"{module}.AsyncOpenAI", return_value=mock_client)


# ── T15-01: "contact for CUST-100" → get_customer_contacts ────────────────────

@pytest.mark.asyncio
async def test_t15_01_contact_for_customer():
    contacts_result = {
        "success": True,
        "data": [
            {
                "contact_id": 1,
                "contact_name": "Alice Smith",
                "designation": "Finance Manager",
                "email": "alice@example.com",
                "phone_number": "+1-555-0100",
            }
        ],
        "row_count": 1,
    }
    resp = _openai_response(_tool_call("get_customer_contacts", {"customer_number": "CUST-100"}))

    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._account.get_customer_contacts",
               new_callable=AsyncMock, return_value=contacts_result) as mock_gc, \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("who is the contact for CUST-100")

    assert result["success"] is True
    assert any(t["tool"] == "get_customer_contacts" for t in result["tools_called"])
    mock_gc.assert_awaited_once_with("CUST-100")
    contact_data = result["results"][0]["result"]["data"][0]
    assert contact_data["contact_name"] == "Alice Smith"
    assert contact_data["email"] == "alice@example.com"
    assert contact_data["phone_number"] == "+1-555-0100"


# ── T15-02: "active customers under EMEA-01" → get_customers_by_company(ACTIVE) ─

@pytest.mark.asyncio
async def test_t15_02_active_customers_by_company():
    customers_result = {
        "success": True,
        "data": [
            {"customer_number": "CUST-001", "customer_name": "Acme Corp", "status": "ACTIVE"},
            {"customer_number": "CUST-002", "customer_name": "Beta Ltd", "status": "ACTIVE"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(
        _tool_call("get_customers_by_company", {"company_code": "EMEA-01", "status": "ACTIVE"})
    )

    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._customer.get_customers_by_company",
               new_callable=AsyncMock, return_value=customers_result) as mock_gc, \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("show me active customers under EMEA-01")

    assert result["success"] is True
    assert any(t["tool"] == "get_customers_by_company" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_customers_by_company")
    assert tc["args"]["company_code"] == "EMEA-01"
    assert tc["args"].get("status", "ACTIVE") == "ACTIVE"
    mock_gc.assert_awaited_once()
    assert result["results"][0]["result"]["row_count"] == 2


# ── T15-03: "products expiring this month" → get_expiring_products(30) ────────

@pytest.mark.asyncio
async def test_t15_03_expiring_products():
    expiring_result = {
        "success": True,
        "data": [
            {"product_code": "PROD-VOI", "customer_number": "CUST-010",
             "end_date": "2026-06-30"},
        ],
        "row_count": 1,
    }
    resp = _openai_response(_tool_call("get_expiring_products", {"days_ahead": 30}))

    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._power.get_expiring_products",
               new_callable=AsyncMock, return_value=expiring_result) as mock_ep, \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("which products are expiring this month")

    assert result["success"] is True
    assert any(t["tool"] == "get_expiring_products" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_expiring_products")
    assert tc["args"].get("days_ahead", 30) == 30
    mock_ep.assert_awaited_once_with(30)


# ── T15-04: "health check for CUST-1042" → get_customer_health_check ──────────

@pytest.mark.asyncio
async def test_t15_04_customer_health_check():
    health_result = {
        "success": True,
        "data": {
            "customer_number": "CUST-1042",
            "flags": {
                "missing_address": False,
                "no_active_products": False,
                "has_unpaid_bills": True,
                "no_events_this_month": False,
            },
        },
    }
    resp = _openai_response(_tool_call("get_customer_health_check", {"customer_number": "CUST-1042"}))

    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=health_result) as mock_hc, \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("run a health check for CUST-1042")

    assert result["success"] is True
    assert any(t["tool"] == "get_customer_health_check" for t in result["tools_called"])
    mock_hc.assert_awaited_once_with("CUST-1042")
    flags = result["results"][0]["result"]["data"]["flags"]
    assert "missing_address" in flags
    assert "has_unpaid_bills" in flags


# ── T15-05: "unpaid bills in USD" → get_unpaid_bills(currency='USD') ──────────

@pytest.mark.asyncio
async def test_t15_05_unpaid_bills_in_usd():
    unpaid_result = {
        "success": True,
        "data": [
            {"invoice_number": "INV-001", "total_amount": 1500.00,
             "currency_code": "USD", "bill_status": "UNPAID"},
            {"invoice_number": "INV-002", "total_amount": 800.00,
             "currency_code": "USD", "bill_status": "OVERDUE"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(_tool_call("get_unpaid_bills", {"currency_code": "USD"}))

    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=unpaid_result) as mock_ub, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("show me unpaid bills in USD")

    assert result["success"] is True
    assert any(t["tool"] == "get_unpaid_bills" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_unpaid_bills")
    assert tc["args"].get("currency_code") == "USD"
    mock_ub.assert_awaited_once()
    assert result["results"][0]["result"]["row_count"] == 2


# ── T15-06: "who raised invoice INV-8821" → get_bill_by_invoice_number ────────

@pytest.mark.asyncio
async def test_t15_06_who_raised_invoice():
    invoice_result = {
        "success": True,
        "data": {
            "invoice_number": "INV-8821",
            "bill_amount": 2500.00,
            "total_amount": 2750.00,
            "bill_status": "UNPAID",
            "account_number": "ACC-001",
            "customer_number": "CUST-100",
        },
        "row_count": 1,
    }
    resp = _openai_response(_tool_call("get_bill_by_invoice_number", {"invoice_number": "INV-8821"}))

    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_bill_by_invoice_number",
               new_callable=AsyncMock, return_value=invoice_result) as mock_gi, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("who raised invoice INV-8821")

    assert result["success"] is True
    assert any(t["tool"] == "get_bill_by_invoice_number" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_bill_by_invoice_number")
    assert tc["args"]["invoice_number"] == "INV-8821"
    mock_gi.assert_awaited_once_with("INV-8821")
    data = result["results"][0]["result"]["data"]
    assert data["invoice_number"] == "INV-8821"
    assert data["customer_number"] == "CUST-100"


# ── T15-07: "due date for account ACC-001" → get_bills_by_account(UNPAID) ─────

@pytest.mark.asyncio
async def test_t15_07_due_date_for_account():
    bills_result = {
        "success": True,
        "data": [
            {"invoice_number": "INV-100", "billing_month": "2026-06-01",
             "total_amount": 3000.00, "bill_status": "UNPAID"},
        ],
        "row_count": 1,
    }
    resp = _openai_response(
        _tool_call("get_bills_by_account", {"account_number": "ACC-001", "status": "UNPAID"})
    )

    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=bills_result) as mock_gb, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("what is the due date for account ACC-001")

    assert result["success"] is True
    assert any(t["tool"] == "get_bills_by_account" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_bills_by_account")
    assert tc["args"]["account_number"] == "ACC-001"
    mock_gb.assert_awaited_once()
    bills = result["results"][0]["result"]["data"]
    assert any(b["bill_status"] == "UNPAID" for b in bills)


# ── T15-08: "revenue for June 2026" → get_monthly_revenue ────────────────────

@pytest.mark.asyncio
async def test_t15_08_revenue_for_june_2026():
    revenue_result = {
        "success": True,
        "data": [
            {"month": "2026-06", "total_revenue": 125000.00, "invoice_count": 42},
            {"month": "2026-05", "total_revenue": 118000.00, "invoice_count": 39},
        ],
        "row_count": 2,
    }
    resp = _openai_response(_tool_call("get_monthly_revenue", {"months": 12}))

    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=revenue_result) as mock_mr, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("what was the revenue for June 2026")

    assert result["success"] is True
    assert any(t["tool"] == "get_monthly_revenue" for t in result["tools_called"])
    mock_mr.assert_awaited_once()
    # June 2026 row should be present in results
    months = result["results"][0]["result"]["data"]
    assert any(m["month"] == "2026-06" for m in months)


# ── T15-09: "total outstanding in USD" → get_unpaid_bills + SUM ───────────────

@pytest.mark.asyncio
async def test_t15_09_total_outstanding_usd():
    unpaid_result = {
        "success": True,
        "data": [
            {"invoice_number": "INV-A", "total_amount": 1000.00, "currency_code": "USD"},
            {"invoice_number": "INV-B", "total_amount": 2500.00, "currency_code": "USD"},
            {"invoice_number": "INV-C", "total_amount": 750.00,  "currency_code": "USD"},
        ],
        "row_count": 3,
    }
    resp = _openai_response(_tool_call("get_unpaid_bills", {"currency_code": "USD"}))

    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=unpaid_result) as mock_ub, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("what is the total outstanding amount in USD")

    assert result["success"] is True
    assert any(t["tool"] == "get_unpaid_bills" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_unpaid_bills")
    assert tc["args"].get("currency_code") == "USD"
    bills = result["results"][0]["result"]["data"]
    total = sum(b["total_amount"] for b in bills)
    assert total == pytest.approx(4250.00)


# ── T15-10: Both agents log correct TOOL_NAME in audit ────────────────────────

@pytest.mark.asyncio
async def test_t15_10_customer_agent_audit_tool_name():
    customers_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    resp = _openai_response(_tool_call("get_customer_summary_stats", {}))
    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._customer.get_customer_summary_stats",
               new_callable=AsyncMock, return_value=customers_result), \
         patch(f"{_CUST_MODULE}.log_audit", audit_mock):
        from src.agents.customer_read_agent import run
        await run("give me customer stats")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "customer_read_agent"


@pytest.mark.asyncio
async def test_t15_10b_billing_agent_audit_tool_name():
    pending_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    resp = _openai_response(_tool_call("get_pending_adjustments", {}))
    with _patch_openai(_BILL_MODULE, resp), \
         patch(f"{_BILL_MODULE}._billing.get_pending_adjustments",
               new_callable=AsyncMock, return_value=pending_result), \
         patch(f"{_BILL_MODULE}.log_audit", audit_mock):
        from src.agents.billing_read_agent import run
        await run("show pending adjustments")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "billing_read_agent"


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t15_customer_agent_openai_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API unavailable"))

    with patch(f"{_CUST_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("show customers")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"
    assert "unavailable" in result["message"]


@pytest.mark.asyncio
async def test_t15_billing_agent_openai_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("rate limit exceeded"))

    with patch(f"{_BILL_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_read_agent import run
        result = await run("show unpaid bills")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"
    assert "rate limit" in result["message"]


@pytest.mark.asyncio
async def test_t15_customer_agent_multiple_tools():
    """Agent can chain get_customer_contacts + get_customer_addresses in one response."""
    contacts_result = {
        "success": True,
        "data": [{"contact_name": "Bob", "email": "bob@x.com", "phone_number": "555-0200"}],
        "row_count": 1,
    }
    addresses_result = {
        "success": True,
        "data": [{"address_type": "BILLING", "address_line1": "123 Main St", "city": "London"}],
        "row_count": 1,
    }
    resp = _openai_response(
        _tool_call("get_customer_contacts", {"customer_number": "CUST-200"}),
        _tool_call("get_customer_addresses", {"customer_number": "CUST-200"}),
    )

    with _patch_openai(_CUST_MODULE, resp), \
         patch(f"{_CUST_MODULE}._account.get_customer_contacts",
               new_callable=AsyncMock, return_value=contacts_result), \
         patch(f"{_CUST_MODULE}._account.get_customer_addresses",
               new_callable=AsyncMock, return_value=addresses_result), \
         patch(f"{_CUST_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.customer_read_agent import run
        result = await run("contacts and addresses for CUST-200")

    assert result["success"] is True
    assert result["row_count"] == 2
    tool_names = [t["tool"] for t in result["tools_called"]]
    assert "get_customer_contacts" in tool_names
    assert "get_customer_addresses" in tool_names


# ── Integration tests (hit real Oracle DB + real OpenAI API) ──────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_01_integration_contact_for_customer(db_conn):
    from src.agents.customer_read_agent import run
    result = await run("who is the contact for CUST-100")
    assert result["success"] is True
    assert any(t["tool"] == "get_customer_contacts" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_02_integration_customers_by_company(db_conn):
    from src.agents.customer_read_agent import run
    result = await run("show me active customers under EMEA-01")
    assert result["success"] is True
    assert any(t["tool"] == "get_customers_by_company" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_03_integration_expiring_products(db_conn):
    from src.agents.customer_read_agent import run
    result = await run("which products are expiring in the next 30 days")
    assert result["success"] is True
    assert any(t["tool"] == "get_expiring_products" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_04_integration_health_check(db_conn):
    from src.agents.customer_read_agent import run
    result = await run("run a health check for CUST-1042")
    assert result["success"] is True
    assert any(t["tool"] == "get_customer_health_check" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_05_integration_unpaid_bills_usd(db_conn):
    from src.agents.billing_read_agent import run
    result = await run("show me unpaid bills in USD")
    assert result["success"] is True
    assert any(t["tool"] == "get_unpaid_bills" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_unpaid_bills")
    assert tc["args"].get("currency_code", "").upper() == "USD"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_06_integration_invoice_lookup(db_conn):
    from src.agents.billing_read_agent import run
    result = await run("look up invoice INV-8821")
    assert result["success"] is True
    assert any(t["tool"] == "get_bill_by_invoice_number" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_07_integration_due_date_for_account(db_conn):
    from src.agents.billing_read_agent import run
    result = await run("what are the unpaid bills for account ACC-001")
    assert result["success"] is True
    assert any(t["tool"] == "get_bills_by_account" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_08_integration_monthly_revenue(db_conn):
    from src.agents.billing_read_agent import run
    result = await run("show me monthly revenue for the last 6 months")
    assert result["success"] is True
    assert any(t["tool"] == "get_monthly_revenue" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t15_10_integration_audit_logs(db_conn):
    from src.agents.customer_read_agent import run as cust_run
    from src.agents.billing_read_agent import run as bill_run
    from src.tools.approval import get_audit_log

    await cust_run("give me customer stats")
    await bill_run("show pending adjustments")

    cust_log = await get_audit_log(tool_name="customer_read_agent", limit=5)
    assert cust_log["success"] is True
    assert cust_log["row_count"] >= 1
    assert all(r["tool_name"] == "customer_read_agent" for r in cust_log["data"])

    bill_log = await get_audit_log(tool_name="billing_read_agent", limit=5)
    assert bill_log["success"] is True
    assert bill_log["row_count"] >= 1
    assert all(r["tool_name"] == "billing_read_agent" for r in bill_log["data"])
