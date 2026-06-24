"""
TASK 22 — billing_run_agent + adjustment_agent
Unit tests: T22-01 through T22-22

All unit tests mock Oracle tool functions and OpenAI client.
Integration tests hit real Oracle DB + real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_BILL_MODULE = "src.agents.billing_run_agent"
_ADJ_MODULE  = "src.agents.adjustment_agent"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _accounts_result(account_numbers: list[str],
                     currency: str = "USD") -> dict:
    return {
        "success": True,
        "data": [
            {"account_number": n, "currency_code": currency,
             "status": "ACTIVE", "billing_cycle": "MONTHLY"}
            for n in account_numbers
        ],
        "row_count": len(account_numbers),
    }


def _anomaly_result(flagged: list[str]) -> dict:
    return {
        "success": True,
        "data": [{"account_number": n, "avg_speed_mbps": 150.0} for n in flagged],
        "row_count": len(flagged),
    }


def _commissioning(billable: bool = True) -> dict:
    return {
        "success": True,
        "data": {"account_number": "ACC-001",
                 "billable_flag": "Y" if billable else "N",
                 "commissioning_date": "2025-01-01",
                 "termination_date": None},
        "row_count": 1,
    }


def _event_summary(count: int = 10) -> dict:
    return {
        "success": True,
        "data": {"event_count": count, "avg_speed_mbps": 50.0},
        "row_count": 1,
    }


def _bill_pending(request_id: int = 99) -> dict:
    return {
        "success": True,
        "request_id": request_id,
        "status": "PENDING",
        "summary": f"Pending: request #{request_id}",
    }


def _adj_tool_call(args: dict) -> MagicMock:
    tc = MagicMock()
    tc.function.name = "create_billing_adjustment"
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_adj_response(args: dict) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = [_adj_tool_call(args)]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai_adj(args: dict):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_adj_response(args))
    return patch(f"{_ADJ_MODULE}.AsyncOpenAI", return_value=mock_client)


# ═══════════════════════════════════════════════════════════════════════════════
# billing_run_agent tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── T22-01: 3 accounts (1 no_flag, 1 no_events, 1 eligible) → queued=1 ────────

@pytest.mark.asyncio
async def test_t22_01_three_accounts_one_eligible():
    accounts = ["ACC-001", "ACC-002", "ACC-003"]

    # ACC-001 → not billable; ACC-002 → 0 events; ACC-003 → eligible
    comm_side_effect = [
        _commissioning(billable=False),   # ACC-001 skipped
        _commissioning(billable=True),    # ACC-002
        _commissioning(billable=True),    # ACC-003
    ]
    event_side_effect = [
        _event_summary(count=0),   # ACC-001 (irrelevant, already skipped)
        _event_summary(count=0),   # ACC-002 → skipped_no_events
        _event_summary(count=15),  # ACC-003 → eligible
    ]

    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(accounts)), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock, side_effect=comm_side_effect), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, side_effect=event_side_effect), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock, return_value=_bill_pending(99)), \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["success"] is True
    assert result["total"] == 3
    assert result["queued"] == 1
    assert "ACC-001" in result["skipped_no_flag"]
    assert "ACC-002" in result["skipped_no_events"]
    assert result["approval_ids"] == [99]


# ── T22-02: eligible account in anomaly list → flagged but still queued ────────

@pytest.mark.asyncio
async def test_t22_02_anomaly_account_flagged_but_billed():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock,
               return_value=_anomaly_result(["ACC-001"])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock, return_value=_commissioning(True)), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary(20)), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock, return_value=_bill_pending(55)), \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["queued"] == 1
    assert "ACC-001" in result["flagged_anomalies"]
    assert result["approval_ids"] == [55]


# ── T22-03: all accounts have no billable flag → queued=0 ────────────────────

@pytest.mark.asyncio
async def test_t22_03_all_skipped_no_flag():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-A", "ACC-B"])), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock,
               side_effect=[_commissioning(False), _commissioning(False)]), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               side_effect=[_event_summary(5), _event_summary(5)]), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock) as mock_bill, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["queued"] == 0
    assert len(result["skipped_no_flag"]) == 2
    mock_bill.assert_not_awaited()


# ── T22-04: all accounts have 0 events → queued=0 ────────────────────────────

@pytest.mark.asyncio
async def test_t22_04_all_skipped_no_events():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-A", "ACC-B"])), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock,
               side_effect=[_commissioning(True), _commissioning(True)]), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               side_effect=[_event_summary(0), _event_summary(0)]), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock) as mock_bill, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["queued"] == 0
    assert len(result["skipped_no_events"]) == 2
    mock_bill.assert_not_awaited()


# ── T22-05: no accounts returned → queued=0, early return ────────────────────

@pytest.mark.asyncio
async def test_t22_05_no_accounts_returns_empty():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value={"success": True, "data": [], "row_count": 0}), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock) as mock_anom, \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["success"] is True
    assert result["total"] == 0
    assert result["queued"] == 0
    # anomalies call happens after account check in our impl — either way result is empty
    assert result["approval_ids"] == []


# ── T22-06: result shape correct ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t22_06_result_shape():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock, return_value=_commissioning(True)), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary(5)), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock, return_value=_bill_pending(1)), \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    required = {"success", "billing_month", "total", "queued",
                "skipped_no_flag", "skipped_no_events",
                "flagged_anomalies", "approval_ids"}
    assert required.issubset(result.keys())
    assert result["billing_month"] == "2026-06"


# ── T22-07: audit tool_name='billing_run_agent', action_type='WRITE' ──────────

@pytest.mark.asyncio
async def test_t22_07_audit_tool_name():
    audit_mock = AsyncMock(return_value=True)

    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value={"success": True, "data": [], "row_count": 0}), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}.log_audit", audit_mock):
        from src.agents.billing_run_agent import run
        await run("2026-06")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "billing_run_agent"
    assert audit_mock.call_args[0][3] == "WRITE"


# ── T22-08: multiple eligible accounts → multiple approval_ids ────────────────

@pytest.mark.asyncio
async def test_t22_08_multiple_eligible_accounts():
    with patch(f"{_BILL_MODULE}._account.get_accounts_by_billing_cycle",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001", "ACC-002", "ACC-003"])), \
         patch(f"{_BILL_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=_anomaly_result([])), \
         patch(f"{_BILL_MODULE}._account.get_account_commissioning_info",
               new_callable=AsyncMock,
               side_effect=[_commissioning(True)] * 3), \
         patch(f"{_BILL_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               side_effect=[_event_summary(5), _event_summary(10), _event_summary(8)]), \
         patch(f"{_BILL_MODULE}._writes.create_bill",
               new_callable=AsyncMock,
               side_effect=[_bill_pending(10), _bill_pending(11), _bill_pending(12)]), \
         patch(f"{_BILL_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.billing_run_agent import run
        result = await run("2026-06")

    assert result["queued"] == 3
    assert result["approval_ids"] == [10, 11, 12]


# ═══════════════════════════════════════════════════════════════════════════════
# adjustment_agent tests
# ═══════════════════════════════════════════════════════════════════════════════

_VALID_ADJ_ARGS = {
    "invoice_number":    "INV-001234",
    "account_number":    "ACC-001",
    "adjustment_type":   "CREDIT",
    "adjustment_amount": 500.0,
    "reason":            "Billing error on June invoice",
    "requested_by":      "finance_user",
}


# ── T22-09: CREDIT adjustment dispatched correctly ────────────────────────────

@pytest.mark.asyncio
async def test_t22_09_credit_adjustment_dispatched():
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 77,
        "status": "PENDING", "summary": "Pending: request #77"
    })

    with _patch_openai_adj(_VALID_ADJ_ARGS), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("apply a $500 credit to INV-001234 for billing error")

    assert result["success"] is True
    assert result["action"] == "create_billing_adjustment"
    assert result["request_id"] == 77
    assert result["status"] == "PENDING"
    mock_write.assert_awaited_once_with(**_VALID_ADJ_ARGS)


# ── T22-10: DISPUTE adjustment dispatched ────────────────────────────────────

@pytest.mark.asyncio
async def test_t22_10_dispute_adjustment_dispatched():
    args = {**_VALID_ADJ_ARGS, "adjustment_type": "DISPUTE", "adjustment_amount": 1200.0}
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 88, "status": "PENDING", "summary": ""
    })

    with _patch_openai_adj(args), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("open a dispute for INV-001234 for $1200")

    assert result["success"] is True
    assert result["request_id"] == 88
    mock_write.assert_awaited_once_with(**args)


# ── T22-11: WAIVER adjustment dispatched ─────────────────────────────────────

@pytest.mark.asyncio
async def test_t22_11_waiver_adjustment_dispatched():
    args = {**_VALID_ADJ_ARGS, "adjustment_type": "WAIVER", "adjustment_amount": 200.0}
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 91, "status": "PENDING", "summary": ""
    })

    with _patch_openai_adj(args), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("waive $200 late fee on INV-001234")

    assert result["success"] is True
    mock_write.assert_awaited_once_with(**args)


# ── T22-12: adjustment_amount = -100 → VALIDATION_ERROR, no DB call ──────────

@pytest.mark.asyncio
async def test_t22_12_negative_amount_validation_error():
    args = {**_VALID_ADJ_ARGS, "adjustment_amount": -100.0}
    mock_write = AsyncMock()

    with _patch_openai_adj(args), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("apply a -$100 credit")

    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    mock_write.assert_not_awaited()


# ── T22-13: adjustment_amount = 0 → VALIDATION_ERROR ────────────────────────

@pytest.mark.asyncio
async def test_t22_13_zero_amount_validation_error():
    args = {**_VALID_ADJ_ARGS, "adjustment_amount": 0}
    mock_write = AsyncMock()

    with _patch_openai_adj(args), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("apply zero adjustment")

    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    mock_write.assert_not_awaited()


# ── T22-14: audit tool_name='adjustment_agent', action_type='WRITE' ──────────

@pytest.mark.asyncio
async def test_t22_14_audit_tool_name_adjustment_agent():
    audit_mock = AsyncMock(return_value=True)
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 55, "status": "PENDING", "summary": ""
    })

    with _patch_openai_adj(_VALID_ADJ_ARGS), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", audit_mock):
        from src.agents.adjustment_agent import run
        await run("apply credit to INV-001234")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "adjustment_agent"
    assert audit_mock.call_args[0][3] == "WRITE"


# ── T22-15: OpenAI failure → OPENAI_ERROR ────────────────────────────────────

@pytest.mark.asyncio
async def test_t22_15_openai_failure():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    with patch(f"{_ADJ_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("apply credit to INV-001234")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T22-16: result shape ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t22_16_result_shape():
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 42, "status": "PENDING",
        "summary": "Pending: request #42"
    })

    with _patch_openai_adj(_VALID_ADJ_ARGS), \
         patch(f"{_ADJ_MODULE}._writes.create_billing_adjustment", mock_write), \
         patch(f"{_ADJ_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.adjustment_agent import run
        result = await run("credit INV-001234")

    required = {"success", "question", "action", "request_id",
                "status", "summary", "details"}
    assert required.issubset(result.keys())
    assert result["action"] == "create_billing_adjustment"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t22_01_integration_billing_run(db_conn):
    from src.agents.billing_run_agent import run
    result = await run("2026-06")
    assert result["success"] is True
    assert "billing_month" in result
    assert isinstance(result["approval_ids"], list)
    assert isinstance(result["skipped_no_flag"], list)
    assert isinstance(result["skipped_no_events"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t22_09_integration_adjustment_credit(db_conn):
    from src.agents.adjustment_agent import run
    result = await run(
        "apply a $500 CREDIT adjustment to invoice INV-000001 "
        "for account ACC-000001 due to billing error"
    )
    assert result["success"] is True
    assert result["action"] == "create_billing_adjustment"
    assert result["request_id"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t22_07_integration_billing_run_audit(db_conn):
    from src.agents.billing_run_agent import run
    from src.tools.approval import get_audit_log
    await run("2026-06")
    log = await get_audit_log(tool_name="billing_run_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t22_14_integration_adjustment_audit(db_conn):
    from src.agents.adjustment_agent import run
    from src.tools.approval import get_audit_log
    # Use mock to avoid needing real invoice
    from unittest.mock import AsyncMock, patch
    args = {**_VALID_ADJ_ARGS}
    mock_write = AsyncMock(return_value={
        "success": True, "request_id": 1, "status": "PENDING", "summary": ""
    })
    with patch("src.agents.adjustment_agent._writes.create_billing_adjustment", mock_write):
        await run("apply credit adjustment")
    log = await get_audit_log(tool_name="adjustment_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
