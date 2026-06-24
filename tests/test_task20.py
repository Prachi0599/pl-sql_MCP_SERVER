"""
TASK 20 — dml_agent + approval_agent
Unit tests: T20-01 through T20-18

All unit tests mock OpenAI (routing) and the underlying write/approval tool functions.
Integration tests hit real Oracle DB + real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_DML_MODULE = "src.agents.dml_agent"
_APR_MODULE  = "src.agents.approval_agent"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _tool_call(name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_response(*tool_calls) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = list(tool_calls)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(module: str, *tool_calls):
    response = _openai_response(*tool_calls)
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    return patch(f"{module}.AsyncOpenAI", return_value=mock_client)


def _pending_result(request_id: int = 42) -> dict:
    return {
        "success": True,
        "request_id": request_id,
        "status": "PENDING",
        "summary": f"Pending approval: request #{request_id}",
        "package_name": "CUSTOMER_PKG",
        "procedure_name": "CREATE_CUSTOMER",
        "action_type": "INSERT",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# dml_agent tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── T20-01: create_customer dispatched → request_id returned ─────────────────

@pytest.mark.asyncio
async def test_t20_01_create_customer_dispatched():
    args = {"customer_name": "ACME Corp", "company_code": "ACME",
            "customer_type_code": "CORP"}
    mock_write = AsyncMock(return_value=_pending_result(42))

    with _patch_openai(_DML_MODULE, _tool_call("create_customer", args)), \
         patch(f"{_DML_MODULE}._writes.create_customer", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("create a new customer called ACME Corp")

    assert result["success"] is True
    assert result["action"] == "create_customer"
    assert result["request_id"] == 42
    assert result["status"] == "PENDING"
    mock_write.assert_awaited_once_with(**args)


# ── T20-02: update_customer_status dispatched ────────────────────────────────

@pytest.mark.asyncio
async def test_t20_02_update_customer_status_dispatched():
    args = {"customer_number": "CUST-001", "new_status": "INACTIVE"}
    mock_write = AsyncMock(return_value=_pending_result(55))

    with _patch_openai(_DML_MODULE, _tool_call("update_customer_status", args)), \
         patch(f"{_DML_MODULE}._writes.update_customer_status", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("deactivate customer CUST-001")

    assert result["action"] == "update_customer_status"
    assert result["request_id"] == 55
    mock_write.assert_awaited_once_with(**args)


# ── T20-03: create_billing_adjustment dispatched ──────────────────────────────

@pytest.mark.asyncio
async def test_t20_03_create_billing_adjustment_dispatched():
    args = {"invoice_number": "INV-001", "account_number": "ACC-001",
            "adjustment_type": "CREDIT", "adjustment_amount": 500.0,
            "reason": "Billing error"}
    mock_write = AsyncMock(return_value=_pending_result(77))

    with _patch_openai(_DML_MODULE, _tool_call("create_billing_adjustment", args)), \
         patch(f"{_DML_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("apply a $500 credit adjustment to INV-001")

    assert result["action"] == "create_billing_adjustment"
    assert result["request_id"] == 77
    mock_write.assert_awaited_once_with(**args)


# ── T20-04: create_bill dispatched ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_04_create_bill_dispatched():
    args = {"account_number": "ACC-001", "bill_amount": 1200.0,
            "tax_amount": 120.0, "currency_code": "USD"}
    mock_write = AsyncMock(return_value=_pending_result(88))

    with _patch_openai(_DML_MODULE, _tool_call("create_bill", args)), \
         patch(f"{_DML_MODULE}._writes.create_bill", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("generate a bill for ACC-001")

    assert result["action"] == "create_bill"
    assert result["request_id"] == 88
    mock_write.assert_awaited_once_with(**args)


# ── T20-05: add_customer_address dispatched ────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_05_add_customer_address_dispatched():
    args = {"customer_number": "CUST-001", "address_type": "BILLING",
            "address_line1": "123 Main St", "city": "Mumbai", "country": "IN"}
    mock_write = AsyncMock(return_value=_pending_result(99))

    with _patch_openai(_DML_MODULE, _tool_call("add_customer_address", args)), \
         patch(f"{_DML_MODULE}._writes.add_customer_address", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("add address for CUST-001")

    assert result["action"] == "add_customer_address"
    mock_write.assert_awaited_once_with(**args)


# ── T20-06: assign_product_to_account dispatched ──────────────────────────────

@pytest.mark.asyncio
async def test_t20_06_assign_product_dispatched():
    args = {"customer_number": "CUST-001", "account_number": "ACC-001",
            "product_code": "MPLS-1G"}
    mock_write = AsyncMock(return_value=_pending_result(110))

    with _patch_openai(_DML_MODULE, _tool_call("assign_product_to_account", args)), \
         patch(f"{_DML_MODULE}._writes.assign_product_to_account", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("assign MPLS-1G to ACC-001 for CUST-001")

    assert result["action"] == "assign_product_to_account"
    mock_write.assert_awaited_once_with(**args)


# ── T20-07: ingest_costed_event dispatched ────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_07_ingest_costed_event_dispatched():
    args = {"account_number": "ACC-001", "event_dtm": "2026-06-01 10:00:00",
            "in_bits": 1000000, "out_bits": 500000,
            "speed_mbps": 50.0, "bandwidth_mbps": 100.0}
    mock_write = AsyncMock(return_value=_pending_result(120))

    with _patch_openai(_DML_MODULE, _tool_call("ingest_costed_event", args)), \
         patch(f"{_DML_MODULE}._writes.ingest_costed_event", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("ingest a usage event for ACC-001")

    assert result["action"] == "ingest_costed_event"
    mock_write.assert_awaited_once_with(**args)


# ── T20-08: mass DML guard — "delete all customers" → MASS_DML_REFUSED ────────

@pytest.mark.asyncio
async def test_t20_08_mass_dml_guard_delete_all():
    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock()

    with patch(f"{_DML_MODULE}.AsyncOpenAI", return_value=mock_openai), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("delete all customers from the database")

    assert result["success"] is False
    assert result["error_code"] == "MASS_DML_REFUSED"
    # No OpenAI call made
    mock_openai.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_t20_08b_mass_dml_guard_update_all():
    with patch(f"{_DML_MODULE}.AsyncOpenAI") as mock_cls, \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("update all accounts to INACTIVE")
    assert result["error_code"] == "MASS_DML_REFUSED"
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_t20_08c_mass_dml_guard_remove_all():
    with patch(f"{_DML_MODULE}.AsyncOpenAI") as mock_cls, \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("remove all billing records")
    assert result["error_code"] == "MASS_DML_REFUSED"
    mock_cls.assert_not_called()


# ── T20-09: audit tool_name='dml_agent' ──────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_09_audit_tool_name_dml_agent():
    audit_mock = AsyncMock(return_value=True)
    args = {"customer_name": "Test Corp", "company_code": "TC",
            "customer_type_code": "CORP"}

    with _patch_openai(_DML_MODULE, _tool_call("create_customer", args)), \
         patch(f"{_DML_MODULE}._writes.create_customer",
               new_callable=AsyncMock, return_value=_pending_result()), \
         patch(f"{_DML_MODULE}.log_audit", audit_mock):
        from src.agents.dml_agent import run
        await run("create customer Test Corp")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "dml_agent"
    assert audit_mock.call_args[0][3] == "WRITE"


# ── T20-10: OpenAI failure → OPENAI_ERROR ─────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_10_openai_failure_returns_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API down"))

    with patch(f"{_DML_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("create a new customer")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T20-11: write tool returns VALIDATION_ERROR → propagated in details ───────

@pytest.mark.asyncio
async def test_t20_11_write_validation_error_propagated():
    args = {"customer_name": "", "company_code": "TC", "customer_type_code": "CORP"}
    mock_write = AsyncMock(return_value={
        "success": False, "error_code": "VALIDATION_ERROR",
        "message": "customer_name is required"
    })

    with _patch_openai(_DML_MODULE, _tool_call("create_customer", args)), \
         patch(f"{_DML_MODULE}._writes.create_customer", mock_write), \
         patch(f"{_DML_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.dml_agent import run
        result = await run("create customer with empty name")

    assert result["success"] is False
    assert result["details"]["error_code"] == "VALIDATION_ERROR"


# ═══════════════════════════════════════════════════════════════════════════════
# approval_agent tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── T20-12: get_pending_approvals dispatched ──────────────────────────────────

@pytest.mark.asyncio
async def test_t20_12_get_pending_approvals_dispatched():
    mock_fn = AsyncMock(return_value={
        "success": True, "data": [{"request_id": 1}, {"request_id": 2}],
        "row_count": 2
    })

    with _patch_openai(_APR_MODULE, _tool_call("get_pending_approvals", {})), \
         patch(f"{_APR_MODULE}._approval.get_pending_approvals", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.approval_agent import run
        result = await run("show me all pending approvals")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "get_pending_approvals"
    assert result["results"][0]["result"]["row_count"] == 2
    mock_fn.assert_awaited_once()


# ── T20-13: approve_request(42, 'admin') dispatched ──────────────────────────

@pytest.mark.asyncio
async def test_t20_13_approve_request_dispatched():
    args = {"request_id": 42, "approved_by": "admin"}
    mock_fn = AsyncMock(return_value={
        "success": True, "request_id": 42, "status": "APPROVED",
        "approved_by": "admin", "dml_result": {"dispatched": True}
    })

    with _patch_openai(_APR_MODULE, _tool_call("approve_request", args)), \
         patch(f"{_APR_MODULE}._approval.approve_request", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.approval_agent import run
        result = await run("approve request 42 as admin")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "approve_request"
    mock_fn.assert_awaited_once_with(request_id=42, approved_by="admin")


# ── T20-14: reject_request dispatched ────────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_14_reject_request_dispatched():
    args = {"request_id": 55, "rejected_by": "admin", "reason": "Duplicate request"}
    mock_fn = AsyncMock(return_value={
        "success": True, "request_id": 55, "status": "REJECTED",
        "rejected_by": "admin", "reason": "Duplicate request"
    })

    with _patch_openai(_APR_MODULE, _tool_call("reject_request", args)), \
         patch(f"{_APR_MODULE}._approval.reject_request", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.approval_agent import run
        result = await run("reject request 55 — duplicate")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "reject_request"
    mock_fn.assert_awaited_once_with(
        request_id=55, rejected_by="admin", reason="Duplicate request")


# ── T20-15: get_my_pending_requests dispatched ────────────────────────────────

@pytest.mark.asyncio
async def test_t20_15_get_my_pending_requests_dispatched():
    args = {"requested_by": "alice"}
    mock_fn = AsyncMock(return_value={
        "success": True, "data": [{"request_id": 10}], "row_count": 1
    })

    with _patch_openai(_APR_MODULE, _tool_call("get_my_pending_requests", args)), \
         patch(f"{_APR_MODULE}._approval.get_my_pending_requests", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.approval_agent import run
        result = await run("show alice's pending requests")

    assert result["tools_called"][0]["tool"] == "get_my_pending_requests"
    mock_fn.assert_awaited_once_with(requested_by="alice")


# ── T20-16: audit tool_name='approval_agent' ─────────────────────────────────

@pytest.mark.asyncio
async def test_t20_16_audit_tool_name_approval_agent():
    audit_mock = AsyncMock(return_value=True)
    mock_fn = AsyncMock(return_value={"success": True, "data": [], "row_count": 0})

    with _patch_openai(_APR_MODULE, _tool_call("get_pending_approvals", {})), \
         patch(f"{_APR_MODULE}._approval.get_pending_approvals", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", audit_mock):
        from src.agents.approval_agent import run
        await run("show pending approvals")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "approval_agent"


# ── T20-17: approval_agent OpenAI failure → OPENAI_ERROR ─────────────────────

@pytest.mark.asyncio
async def test_t20_17_approval_agent_openai_failure():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    with patch(f"{_APR_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_APR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.approval_agent import run
        result = await run("list pending approvals")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T20-18: approve_request audit action_type='WRITE' ────────────────────────

@pytest.mark.asyncio
async def test_t20_18_approve_audit_action_type_write():
    audit_mock = AsyncMock(return_value=True)
    args = {"request_id": 10, "approved_by": "manager"}
    mock_fn = AsyncMock(return_value={
        "success": True, "request_id": 10, "status": "APPROVED",
        "dml_result": {"dispatched": True}
    })

    with _patch_openai(_APR_MODULE, _tool_call("approve_request", args)), \
         patch(f"{_APR_MODULE}._approval.approve_request", mock_fn), \
         patch(f"{_APR_MODULE}.log_audit", audit_mock):
        from src.agents.approval_agent import run
        await run("approve request 10")

    assert audit_mock.call_args[0][3] == "WRITE"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t20_01_integration_dml_create_customer(db_conn):
    from src.agents.dml_agent import run
    result = await run(
        "create a new customer named 'Integration Test Corp' "
        "with company code INV0001 and customer type CORP"
    )
    assert result["success"] is True
    assert result["action"] == "create_customer"
    assert result["request_id"] is not None
    assert result["status"] == "PENDING"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t20_08_integration_mass_dml_blocked(db_conn):
    from src.agents.dml_agent import run
    result = await run("delete all customers")
    assert result["success"] is False
    assert result["error_code"] == "MASS_DML_REFUSED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t20_12_integration_get_pending_approvals(db_conn):
    from src.agents.approval_agent import run
    result = await run("show me all pending approval requests")
    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "get_pending_approvals"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t20_09_integration_dml_audit_log(db_conn):
    from src.agents.dml_agent import run
    from src.tools.approval import get_audit_log
    await run("create a new currency with code XXX and name Test Currency")
    log = await get_audit_log(tool_name="dml_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t20_16_integration_approval_audit_log(db_conn):
    from src.agents.approval_agent import run
    from src.tools.approval import get_audit_log
    await run("list all pending approvals")
    log = await get_audit_log(tool_name="approval_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
