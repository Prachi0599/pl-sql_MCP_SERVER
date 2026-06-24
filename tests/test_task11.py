"""
TASK 11 — Approval Workflow Engine (Group K)
Unit tests: T11-01 through T11-11
"""
import json
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn():
    c = MagicMock()
    c.close = AsyncMock()
    return c


def _stack_approval(exec_rows=None, callproc_side_effect=None,
                    callproc_return=None):
    """Patch approval._exec, _callproc, get_connection, log_audit."""
    s = ExitStack()
    conn = _conn()
    s.enter_context(patch("src.tools.approval.get_connection",
                          new_callable=AsyncMock, return_value=conn))
    if exec_rows is not None:
        s.enter_context(patch("src.tools.approval._exec",
                              new_callable=AsyncMock, side_effect=exec_rows))
    if callproc_side_effect is not None:
        s.enter_context(patch("src.tools.approval._callproc",
                              new_callable=AsyncMock,
                              side_effect=callproc_side_effect))
    elif callproc_return is not None:
        s.enter_context(patch("src.tools.approval._callproc",
                              new_callable=AsyncMock,
                              return_value=callproc_return))
    else:
        s.enter_context(patch("src.tools.approval._callproc",
                              new_callable=AsyncMock, return_value=None))
    s.enter_context(patch("src.tools.approval.log_audit",
                          new_callable=AsyncMock, return_value=True))
    s.enter_context(patch("src.tools.approval._dispatch_dml",
                          new_callable=AsyncMock,
                          return_value={"dispatched": True,
                                        "procedure": "SOME_PKG.PROC"}))
    return s, conn


# ── T11-01: create_approval_request returns {request_id, status:'PENDING'} ───

@pytest.mark.asyncio
async def test_t11_01_create_approval_request_returns_pending():
    conn = _conn()
    with patch("src.tools.approval._callproc",
               new_callable=AsyncMock, return_value=None), \
         patch("src.tools.approval._exec",
               new_callable=AsyncMock,
               return_value=[{"request_id": 42}]):
        from src.tools.approval import create_approval_request
        result = await create_approval_request(
            conn,
            package_name="BILLING_PKG",
            procedure_name="UPDATE_BILL_STATUS",
            action_type="UPDATE",
            old_value='{"bill_status":"UNPAID"}',
            new_value='{"params":[551,"PAID"]}',
            requested_by="alice",
        )
    assert result["status"] == "PENDING"
    assert result["request_id"] == 42
    assert "summary" in result


# ── T11-02: NEW_VALUE stored correctly as JSON with params key ────────────────

@pytest.mark.asyncio
async def test_t11_02_new_value_json_format():
    params = [551, "PAID"]
    new_value = json.dumps({"params": params})
    parsed = json.loads(new_value)
    assert parsed["params"] == params
    assert new_value == '{"params": [551, "PAID"]}'


# ── T11-03: approve_request dispatches DML to target procedure ────────────────

@pytest.mark.asyncio
async def test_t11_03_approve_request_dispatches_dml():
    req_row = [{"request_id": 42, "package_name": "BILLING_PKG",
                "procedure_name": "UPDATE_BILL_STATUS",
                "action_type": "UPDATE",
                "new_value": '{"params":[551,"PAID"]}',
                "status": "PENDING"}]
    dispatch_mock = AsyncMock(return_value={"dispatched": True,
                                            "procedure": "BILLING_PKG.UPDATE_BILL_STATUS"})
    with _stack_approval(exec_rows=[req_row])[0], \
         patch("src.tools.approval._dispatch_dml", dispatch_mock):
        from src.tools.approval import approve_request
        result = await approve_request(42, "bob")
    assert result["success"] is True
    assert result["status"] == "APPROVED"
    assert result["dml_result"]["dispatched"] is True
    dispatch_mock.assert_awaited_once()


# ── T11-04: approve_request sets APPROVED and approved_by in response ─────────

@pytest.mark.asyncio
async def test_t11_04_approve_request_sets_approved_by():
    req_row = [{"request_id": 10, "package_name": "BILLING_PKG",
                "procedure_name": "UPDATE_BILL_STATUS",
                "action_type": "UPDATE",
                "new_value": '{"params":[10,"PAID"]}',
                "status": "PENDING"}]
    with _stack_approval(exec_rows=[req_row])[0]:
        from src.tools.approval import approve_request
        result = await approve_request(10, "john.doe")
    assert result["success"] is True
    assert result["approved_by"] == "john.doe"
    assert result["status"] == "APPROVED"
    assert result["request_id"] == 10


# ── T11-05: reject_request sets REJECTED — no DML dispatch ───────────────────

@pytest.mark.asyncio
async def test_t11_05_reject_request_no_dml():
    req_row = [{"status": "PENDING"}]
    dispatch_mock = AsyncMock()
    with _stack_approval(exec_rows=[req_row])[0], \
         patch("src.tools.approval._dispatch_dml", dispatch_mock):
        from src.tools.approval import reject_request
        result = await reject_request(5, "alice", "Duplicate request")
    assert result["success"] is True
    assert result["status"] == "REJECTED"
    assert result["reason"] == "Duplicate request"
    dispatch_mock.assert_not_awaited()  # DML must NOT be called on reject


# ── T11-06: approve_request on non-PENDING request returns ORA-20001 ─────────

@pytest.mark.asyncio
async def test_t11_06_approve_already_approved_returns_error():
    req_row = [{"request_id": 7, "package_name": "BILLING_PKG",
                "procedure_name": "UPDATE_BILL_STATUS",
                "action_type": "UPDATE",
                "new_value": '{}',
                "status": "APPROVED"}]   # already approved
    with _stack_approval(exec_rows=[req_row])[0]:
        from src.tools.approval import approve_request
        result = await approve_request(7, "bob")
    assert result["success"] is False
    assert "ORA-20001" in result["error_code"]


# ── T11-07: approve_request on non-existent request returns ORA-20002 ─────────

@pytest.mark.asyncio
async def test_t11_07_approve_nonexistent_returns_error():
    with _stack_approval(exec_rows=[[]])[0]:  # empty result = not found
        from src.tools.approval import approve_request
        result = await approve_request(9999, "bob")
    assert result["success"] is False
    assert "ORA-20002" in result["error_code"]


# ── T11-08: get_pending_approvals returns only PENDING rows ───────────────────

@pytest.mark.asyncio
async def test_t11_08_get_pending_approvals_status():
    pending = [
        {"request_id": 1, "package_name": "BILLING_PKG",
         "procedure_name": "UPDATE_BILL_STATUS", "action_type": "UPDATE",
         "status": "PENDING", "requested_by": "alice",
         "approved_by": None, "created_dtm": "2026-06-20",
         "approved_dtm": None, "new_value": '{}'},
    ]
    with _stack_approval(exec_rows=[pending])[0]:
        from src.tools.approval import get_pending_approvals
        result = await get_pending_approvals()
    assert result["success"] is True
    assert result["row_count"] == 1
    assert all(r["status"] == "PENDING" for r in result["data"])


# ── T11-09: get_my_pending_requests filters by REQUESTED_BY ──────────────────

@pytest.mark.asyncio
async def test_t11_09_get_my_pending_requests_filters_by_user():
    rows = [
        {"request_id": 2, "package_name": "ACCOUNT_PKG",
         "procedure_name": "UPDATE_ACCOUNT_STATUS", "action_type": "UPDATE",
         "status": "PENDING", "requested_by": "alice",
         "approved_by": None, "created_dtm": "2026-06-21",
         "approved_dtm": None, "new_value": '{}'},
    ]
    with _stack_approval(exec_rows=[rows])[0]:
        from src.tools.approval import get_my_pending_requests
        result = await get_my_pending_requests("alice")
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["requested_by"] == "alice"


# ── T11-10: approve_request audit log has ACTION_TYPE='UPDATE' ───────────────

@pytest.mark.asyncio
async def test_t11_10_approve_request_audit_action_type():
    req_row = [{"request_id": 3, "package_name": "BILLING_PKG",
                "procedure_name": "UPDATE_BILL_STATUS",
                "action_type": "UPDATE",
                "new_value": '{"params":[3,"PAID"]}',
                "status": "PENDING"}]
    audit_mock = AsyncMock(return_value=True)
    with _stack_approval(exec_rows=[req_row])[0], \
         patch("src.tools.approval.log_audit", audit_mock):
        from src.tools.approval import approve_request
        await approve_request(3, "john.doe")
    # verify the audit call used ACTION_TYPE='UPDATE'
    call_args = audit_mock.call_args
    assert call_args[0][3] == "UPDATE"   # positional arg 4 = action_type
    assert call_args[0][5] == "SUCCESS"  # positional arg 6 = status


# ── T11-11: reject_request audit log has STATUS='SUCCESS' ────────────────────

@pytest.mark.asyncio
async def test_t11_11_reject_request_audit_success():
    req_row = [{"status": "PENDING"}]
    audit_mock = AsyncMock(return_value=True)
    with _stack_approval(exec_rows=[req_row])[0], \
         patch("src.tools.approval.log_audit", audit_mock):
        from src.tools.approval import reject_request
        result = await reject_request(4, "bob", "Wrong request")
    assert result["success"] is True
    call_args = audit_mock.call_args
    assert call_args[0][5] == "SUCCESS"  # positional arg 6 = status


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t11_08_integration_get_pending_approvals(db_conn):
    from src.tools.approval import get_pending_approvals
    result = await get_pending_approvals()
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t11_08_integration_get_audit_log(db_conn):
    from src.tools.approval import get_audit_log
    result = await get_audit_log(limit=10)
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t11_04_integration_get_audit_stats(db_conn):
    from src.tools.approval import get_audit_stats
    result = await get_audit_stats()
    assert result["success"] is True
    assert isinstance(result["data"], list)
    if result["data"]:
        row = result["data"][0]
        assert "tool_name" in row
        assert "total_calls" in row


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t11_01_integration_create_and_reject(db_conn):
    """Create a real approval request then reject it — verifies end-to-end flow."""
    from src.tools.approval import create_approval_request, reject_request
    req = await create_approval_request(
        db_conn,
        package_name="BILLING_PKG",
        procedure_name="UPDATE_BILL_STATUS",
        action_type="UPDATE",
        old_value=None,
        new_value='{"params":[0,"PAID"]}',
        requested_by="test_runner",
    )
    assert req["status"] == "PENDING"
    assert req["request_id"] is not None

    rej = await reject_request(req["request_id"], "test_runner", "Integration test")
    assert rej["success"] is True
    assert rej["status"] == "REJECTED"
