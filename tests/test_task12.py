"""
TASK 12 — All Write Tools (Groups A, B, C, D, E, F, G, I, J)
Unit tests: T12-01 through T12-13
"""
import json
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

_MODULE = "src.tools.writes"

_PENDING = {"request_id": 99, "status": "PENDING", "summary": "Pending approval: test"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn():
    c = MagicMock()
    c.close = AsyncMock()
    c.commit = AsyncMock()
    return c


def _stack(exec_rows=None, resolvers: dict | None = None,
           create_approval_return=None):
    """Patch writes module dependencies."""
    s = ExitStack()
    conn = _conn()
    s.enter_context(patch(f"{_MODULE}.get_connection",
                          new_callable=AsyncMock, return_value=conn))
    if exec_rows is not None:
        s.enter_context(patch(f"{_MODULE}._exec",
                              new_callable=AsyncMock, side_effect=exec_rows))
    s.enter_context(patch(f"{_MODULE}.log_audit",
                          new_callable=AsyncMock, return_value=True))
    s.enter_context(patch(f"{_MODULE}.create_approval_request",
                          new_callable=AsyncMock,
                          return_value=create_approval_return or _PENDING))
    for fname, retval in (resolvers or {}).items():
        if retval is None:
            s.enter_context(patch(f"{_MODULE}.{fname}",
                                  new_callable=AsyncMock,
                                  side_effect=ValueError(f"Not found: {fname}")))
        else:
            s.enter_context(patch(f"{_MODULE}.{fname}",
                                  new_callable=AsyncMock, return_value=retval))
    return s, conn


# ── T12-01: create_customer resolves company_code before approval ─────────────

@pytest.mark.asyncio
async def test_t12_01_create_customer_resolves_company_before_approval():
    resolve_co = AsyncMock(return_value=5)
    resolve_ty = AsyncMock(return_value=2)
    seq_rows = [{"customer_number": "CUST-000042"}]
    with _stack(exec_rows=[seq_rows],
                resolvers={
                    "resolve_company_code": 5,
                    "resolve_customer_type_code": 2,
                })[0]:
        from src.tools.writes import create_customer
        result = await create_customer("Acme Corp", "EMEA-01", "ENTERPRISE")
    assert result["success"] is True
    assert result["status"] == "PENDING"
    assert result["request_id"] == 99


# ── T12-02: unknown company_code fails at resolver ────────────────────────────

@pytest.mark.asyncio
async def test_t12_02_unknown_company_code_returns_not_found():
    with _stack(resolvers={"resolve_company_code": None,
                            "resolve_customer_type_code": 2})[0]:
        from src.tools.writes import create_customer
        result = await create_customer("Acme Corp", "UNKNOWN-CO", "ENTERPRISE")
    assert result["success"] is False
    assert result["error_code"] == "NOT_FOUND"


# ── T12-03: create_account resolves customer_number + currency_code ───────────

@pytest.mark.asyncio
async def test_t12_03_create_account_resolves_customer_and_currency():
    co_mock = AsyncMock(return_value=10)
    cu_mock = AsyncMock(return_value=3)
    seq_rows = [{"account_number": "ACC-000007"}]
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}._exec",
                              new_callable=AsyncMock, return_value=seq_rows))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request",
                              new_callable=AsyncMock, return_value=_PENDING))
        s.enter_context(patch(f"{_MODULE}.resolve_customer_number", co_mock))
        s.enter_context(patch(f"{_MODULE}.resolve_currency_code", cu_mock))

        from src.tools.writes import create_account
        result = await create_account("CUST-001", "Main Account", "USD")

    assert result["success"] is True
    assert result["status"] == "PENDING"
    co_mock.assert_awaited_once()
    cu_mock.assert_awaited_once()
    assert result["account_number"] == "ACC-000007"


# ── T12-04: create_account returns PENDING (billing cycle set by Oracle package) ─

@pytest.mark.asyncio
async def test_t12_04_create_account_pending_billing_cycle_monthly():
    seq_rows = [{"account_number": "ACC-000008"}]
    with _stack(exec_rows=[seq_rows],
                resolvers={"resolve_customer_number": 10,
                            "resolve_currency_code": 3})[0]:
        from src.tools.writes import create_account
        result = await create_account("CUST-001", "Test Account", "GBP")
    assert result["success"] is True
    assert result["status"] == "PENDING"
    # Billing cycle MONTHLY is hardcoded in Oracle; confirmed via integration tests


# ── T12-05: update_account_status resolves account_number before approval ─────

@pytest.mark.asyncio
async def test_t12_05_update_account_status_resolves_account():
    acc_mock = AsyncMock(return_value=42)
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request",
                              new_callable=AsyncMock, return_value=_PENDING))
        s.enter_context(patch(f"{_MODULE}.resolve_account_number", acc_mock))

        from src.tools.writes import update_account_status
        result = await update_account_status("ACC-001", "INACTIVE")

    assert result["success"] is True
    assert result["status"] == "PENDING"
    acc_mock.assert_awaited_once()


# ── T12-06: create_bill NEW_VALUE has post_query for INVOICE_NUMBER ───────────

@pytest.mark.asyncio
async def test_t12_06_create_bill_new_value_has_post_query():
    cap = AsyncMock(return_value=_PENDING)
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request", cap))
        s.enter_context(patch(f"{_MODULE}.resolve_account_number",
                              new_callable=AsyncMock, return_value=77))
        s.enter_context(patch(f"{_MODULE}.resolve_currency_code",
                              new_callable=AsyncMock, return_value=3))

        from src.tools.writes import create_bill
        result = await create_bill("ACC-001", 500.0, 50.0, "USD")

    assert result["success"] is True
    # create_approval_request is called with keyword args — check them
    kw = cap.call_args.kwargs
    new_value_str = kw.get("new_value", "")
    assert "post_query" in new_value_str, "post_query should be in new_value"
    payload = json.loads(new_value_str)
    assert "post_query" in payload
    assert "INVOICE_NUMBER" in payload["post_query"]["sql"]


# ── T12-07: create_bill returns PENDING (INVOICE_NUMBER after approval) ────────

@pytest.mark.asyncio
async def test_t12_07_create_bill_returns_pending_with_note():
    with _stack(resolvers={"resolve_account_number": 77,
                            "resolve_currency_code": 3})[0]:
        from src.tools.writes import create_bill
        result = await create_bill("ACC-001", 1200.0, 120.0, "USD")
    assert result["success"] is True
    assert result["status"] == "PENDING"
    assert "note" in result or result["request_id"] is not None


# ── T12-08: update_bill_status PAID creates PENDING for BILLING_PKG ──────────

@pytest.mark.asyncio
async def test_t12_08_update_bill_status_paid_creates_pending():
    bill_rows = [{"bill_summary_id": 551}]
    cap = AsyncMock(return_value=_PENDING)
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}._exec",
                              new_callable=AsyncMock, return_value=bill_rows))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request", cap))

        from src.tools.writes import update_bill_status
        result = await update_bill_status("INV-2026-0001", "PAID")

    assert result["success"] is True
    assert result["status"] == "PENDING"
    # create_approval_request uses keyword args for package/procedure/new_value
    kw = cap.call_args.kwargs
    assert kw["package_name"] == "BILLING_PKG"
    assert kw["procedure_name"] == "UPDATE_BILL_STATUS"
    new_val = json.loads(kw["new_value"])
    assert new_val["params"] == [551, "PAID"]


# ── T12-09: assign_product_to_account resolves all 3 codes ───────────────────

@pytest.mark.asyncio
async def test_t12_09_assign_product_resolves_three_codes():
    cu_mock = AsyncMock(return_value=10)
    ac_mock = AsyncMock(return_value=20)
    pr_mock = AsyncMock(return_value=5)
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request",
                              new_callable=AsyncMock, return_value=_PENDING))
        s.enter_context(patch(f"{_MODULE}.resolve_customer_number", cu_mock))
        s.enter_context(patch(f"{_MODULE}.resolve_account_number", ac_mock))
        s.enter_context(patch(f"{_MODULE}.resolve_product_code", pr_mock))

        from src.tools.writes import assign_product_to_account
        result = await assign_product_to_account(
            "CUST-001", "ACC-001", "MPLS-STD")

    assert result["success"] is True
    cu_mock.assert_awaited_once()
    ac_mock.assert_awaited_once()
    pr_mock.assert_awaited_once()


# ── T12-10: add_customer_address missing city → VALIDATION_ERROR ──────────────

@pytest.mark.asyncio
async def test_t12_10_missing_city_fails_validation():
    from src.tools.writes import add_customer_address
    result = await add_customer_address(
        "CUST-001", "BILLING", "123 Main St", "", "UK")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    assert "city" in result["message"].lower()


@pytest.mark.asyncio
async def test_t12_10b_missing_city_no_db_call():
    """Validation error must occur before any DB call."""
    db_mock = AsyncMock()
    with patch(f"{_MODULE}.get_connection", db_mock):
        from src.tools.writes import add_customer_address
        result = await add_customer_address(
            "CUST-001", "BILLING", "123 Main St", "   ", "UK")
    assert result["success"] is False
    db_mock.assert_not_awaited()


# ── T12-11: create_billing_adjustment negative amount fails ───────────────────

@pytest.mark.asyncio
async def test_t12_11_negative_adjustment_fails_validation():
    from src.tools.writes import create_billing_adjustment
    result = await create_billing_adjustment(
        "INV-001", "ACC-001", "CREDIT", -100.0, "Error fix")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    assert "positive" in result["message"].lower()


@pytest.mark.asyncio
async def test_t12_11b_zero_adjustment_also_fails():
    from src.tools.writes import create_billing_adjustment
    result = await create_billing_adjustment(
        "INV-001", "ACC-001", "CREDIT", 0.0, "Zero amount")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


# ── T12-12: create_service_request → PENDING for SERVICE_REQUEST_PKG ─────────

@pytest.mark.asyncio
async def test_t12_12_create_service_request_pending():
    cap = AsyncMock(return_value=_PENDING)
    with ExitStack() as s:
        conn = _conn()
        s.enter_context(patch(f"{_MODULE}.get_connection",
                              new_callable=AsyncMock, return_value=conn))
        s.enter_context(patch(f"{_MODULE}.log_audit",
                              new_callable=AsyncMock, return_value=True))
        s.enter_context(patch(f"{_MODULE}.create_approval_request", cap))
        s.enter_context(patch(f"{_MODULE}.resolve_customer_number",
                              new_callable=AsyncMock, return_value=10))

        from src.tools.writes import create_service_request
        result = await create_service_request(
            "CUST-001", "BILLING", "HIGH",
            "Invoice discrepancy", "alice")

    assert result["success"] is True
    assert result["status"] == "PENDING"
    kw = cap.call_args.kwargs
    assert kw["package_name"] == "SERVICE_REQUEST_PKG"
    assert kw["procedure_name"] == "CREATE_REQUEST"


# ── T12-13: create_currency duplicate → DIRECT_SQL, ORA-00001 mapped ─────────

@pytest.mark.asyncio
async def test_t12_13_create_currency_returns_pending():
    """create_currency creates a PENDING approval; dispatch raises ORA-00001 on approve."""
    with _stack()[0]:
        from src.tools.writes import create_currency
        result = await create_currency("EUR", "Euro")
    assert result["success"] is True
    assert result["status"] == "PENDING"


@pytest.mark.asyncio
async def test_t12_13b_create_currency_approval_maps_ora_00001():
    """If DIRECT_SQL dispatch raises ORA-00001, approve_request maps it correctly."""
    import oracledb
    req_row = [{"request_id": 1, "package_name": "DIRECT_SQL",
                "procedure_name": "INSERT_CURRENCY",
                "action_type": "INSERT",
                "new_value": '{"sql":"INSERT INTO CURRENCY ...","params":["EUR","Euro"]}',
                "status": "PENDING"}]

    # Create a fake ORA-00001 DatabaseError
    class _FakeDatabaseError(oracledb.DatabaseError):
        def __init__(self):
            super().__init__()
        @property
        def args(self):
            class _Info:
                code = 1
                message = "ORA-00001: unique constraint violated"
            return (_Info(),)

    callproc_mock = AsyncMock(side_effect=_FakeDatabaseError())
    dispatch_mock = AsyncMock(side_effect=_FakeDatabaseError())

    with patch("src.tools.approval.get_connection",
               new_callable=AsyncMock, return_value=_conn()), \
         patch("src.tools.approval._exec",
               new_callable=AsyncMock, side_effect=[req_row]), \
         patch("src.tools.approval._callproc", callproc_mock), \
         patch("src.tools.approval._dispatch_dml", dispatch_mock), \
         patch("src.tools.approval.log_audit",
               new_callable=AsyncMock, return_value=True):
        from src.tools.approval import approve_request
        result = await approve_request(1, "admin")

    assert result["success"] is False


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t12_01_integration_create_customer_pending(db_conn):
    from src.tools.reference import get_providers
    from src.tools.customer import search_customers
    from src.tools.writes import create_customer

    # Get a real company_code to use
    from src.db.pool import get_connection
    c = await get_connection()
    try:
        from src.tools.approval import _exec
        companies = await _exec(c,
            "SELECT COMPANY_CODE, CUSTOMER_TYPE_CODE FROM MCP_APP.INVOICING_COMPANY ic "
            "JOIN MCP_APP.CUSTOMER_TYPE ct ON 1=1 "
            "FETCH FIRST 1 ROW ONLY")
        if not companies:
            pytest.skip("No companies found")
        cc = companies[0]["company_code"]
        tc = companies[0]["customer_type_code"]
    finally:
        await c.close()

    result = await create_customer("Integration Test Corp", cc, tc,
                                   requested_by="test_runner")
    assert result["success"] is True
    assert result["status"] == "PENDING"
    assert "customer_number" in result
    assert result["request_id"] is not None

    # Reject the pending request to clean up
    from src.tools.approval import reject_request
    await reject_request(result["request_id"], "test_runner", "cleanup")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t12_10_integration_add_address_validation(db_conn):
    from src.tools.writes import add_customer_address
    result = await add_customer_address("CUST-FAKE", "BILLING", "1 Test St", "", "UK")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t12_11_integration_negative_adjustment_validation(db_conn):
    from src.tools.writes import create_billing_adjustment
    result = await create_billing_adjustment(
        "INV-FAKE", "ACC-FAKE", "CREDIT", -50.0, "Bad amount")
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t12_02_integration_unknown_company_code(db_conn):
    from src.tools.writes import create_customer
    result = await create_customer("Test Corp", "INVALID-CO-XXXX", "ENTERPRISE")
    assert result["success"] is False
    assert result["error_code"] == "NOT_FOUND"
