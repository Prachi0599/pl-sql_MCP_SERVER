"""
TASK 16 — usage_read_agent + operations_read_agent
Unit tests: T16-01 through T16-10

All unit tests mock the OpenAI client so no real API calls are made.
Integration tests hit both the real Oracle DB and the real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_USAGE_MODULE = "src.agents.usage_read_agent"
_OPS_MODULE   = "src.agents.operations_read_agent"


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


# ── T16-01: "usage for ACC-8821 this month" → get_events_by_account ───────────

@pytest.mark.asyncio
async def test_t16_01_events_by_account_with_date_range():
    events_result = {
        "success": True,
        "data": [
            {"event_id": 1, "account_num": "ACC-8821", "speed_mbps": 45.2,
             "event_dtm": "2026-06-15T10:00:00"},
            {"event_id": 2, "account_num": "ACC-8821", "speed_mbps": 52.7,
             "event_dtm": "2026-06-16T11:00:00"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(
        _tool_call("get_events_by_account",
                   {"account_number": "ACC-8821",
                    "date_from": "2026-06-01",
                    "date_to": "2026-06-30"})
    )

    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_events_by_account",
               new_callable=AsyncMock, return_value=events_result) as mock_ev, \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("show me usage for ACC-8821 this month")

    assert result["success"] is True
    assert any(t["tool"] == "get_events_by_account" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_events_by_account")
    assert tc["args"]["account_number"] == "ACC-8821"
    assert "date_from" in tc["args"]
    mock_ev.assert_awaited_once()
    assert result["results"][0]["result"]["row_count"] == 2


# ── T16-02: "top 10 accounts by usage" → get_top_usage_accounts(10) ───────────

@pytest.mark.asyncio
async def test_t16_02_top_10_accounts_by_usage():
    top_result = {
        "success": True,
        "data": [
            {"account_number": f"ACC-{i:03d}",
             "total_bits": 1000000 - i * 1000,
             "avg_speed_mbps": 95.0 - i}
            for i in range(10)
        ],
        "row_count": 10,
    }
    resp = _openai_response(_tool_call("get_top_usage_accounts", {"limit": 10}))

    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=top_result) as mock_top, \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("show me the top 10 accounts by usage")

    assert result["success"] is True
    assert any(t["tool"] == "get_top_usage_accounts" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_top_usage_accounts")
    assert tc["args"].get("limit", 10) == 10
    mock_top.assert_awaited_once_with(10)
    assert result["results"][0]["result"]["row_count"] == 10


# ── T16-03: "accounts exceeding 100 Mbps" → get_usage_anomalies(100) ──────────

@pytest.mark.asyncio
async def test_t16_03_usage_anomalies_threshold():
    anomalies_result = {
        "success": True,
        "data": [
            {"account_number": "ACC-010", "speed_mbps": 145.3},
            {"account_number": "ACC-025", "speed_mbps": 128.7},
        ],
        "row_count": 2,
    }
    resp = _openai_response(_tool_call("get_usage_anomalies", {"threshold_mbps": 100}))

    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_usage_anomalies",
               new_callable=AsyncMock, return_value=anomalies_result) as mock_an, \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("which accounts are exceeding 100 Mbps")

    assert result["success"] is True
    assert any(t["tool"] == "get_usage_anomalies" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_usage_anomalies")
    assert tc["args"].get("threshold_mbps", 100) == 100
    mock_an.assert_awaited_once_with(threshold_mbps=100)
    assert result["results"][0]["result"]["row_count"] == 2


# ── T16-04: "failed events from MEDIATION today" → get_events_by_source_system + get_failed_events ─

@pytest.mark.asyncio
async def test_t16_04_failed_events_from_source_system():
    source_result = {
        "success": True,
        "data": [
            {"event_id": 11, "source_system": "MEDIATION", "status": "FAILED"},
        ],
        "row_count": 1,
    }
    failed_result = {
        "success": True,
        "data": [
            {"event_id": 11, "source_system": "MEDIATION", "status": "FAILED"},
            {"event_id": 22, "source_system": "MEDIATION", "status": "ERROR"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(
        _tool_call("get_events_by_source_system",
                   {"source_system": "MEDIATION", "status": "FAILED"}),
        _tool_call("get_failed_events", {"source_system": "MEDIATION"}),
    )

    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_events_by_source_system",
               new_callable=AsyncMock, return_value=source_result) as mock_src, \
         patch(f"{_USAGE_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=failed_result) as mock_fe, \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("show me failed events from MEDIATION today")

    assert result["success"] is True
    assert result["row_count"] == 2
    tool_names = [t["tool"] for t in result["tools_called"]]
    assert "get_events_by_source_system" in tool_names
    assert "get_failed_events" in tool_names
    # Both tools should be called with MEDIATION as source system
    src_tc = next(t for t in result["tools_called"]
                  if t["tool"] == "get_events_by_source_system")
    assert src_tc["args"]["source_system"] == "MEDIATION"
    mock_src.assert_awaited_once()
    mock_fe.assert_awaited_once()


# ── T16-05: "bandwidth trend for ACC-001 by day" → get_bandwidth_trend('DAY') ─

@pytest.mark.asyncio
async def test_t16_05_bandwidth_trend_by_day():
    trend_result = {
        "success": True,
        "data": [
            {"period": "2026-06-24", "avg_speed_mbps": 67.3, "event_count": 12},
            {"period": "2026-06-23", "avg_speed_mbps": 71.8, "event_count": 15},
        ],
        "row_count": 2,
    }
    resp = _openai_response(
        _tool_call("get_bandwidth_trend",
                   {"account_number": "ACC-001", "granularity": "DAY"})
    )

    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_bandwidth_trend",
               new_callable=AsyncMock, return_value=trend_result) as mock_bt, \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("show me the bandwidth trend for ACC-001 by day")

    assert result["success"] is True
    assert any(t["tool"] == "get_bandwidth_trend" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_bandwidth_trend")
    assert tc["args"].get("account_number") == "ACC-001"
    assert tc["args"].get("granularity", "DAY") == "DAY"
    mock_bt.assert_awaited_once()
    data = result["results"][0]["result"]["data"]
    assert data[0]["period"] == "2026-06-24"


# ── T16-06: "did all systems send data today" → get_load_status_today ─────────

@pytest.mark.asyncio
async def test_t16_06_load_status_today():
    load_result = {
        "success": True,
        "data": [
            {"source_system": "MEDIATION", "records_received": 500,
             "records_loaded": 498, "records_failed": 2, "status": "PARTIAL"},
            {"source_system": "RATING",    "records_received": 800,
             "records_loaded": 800, "records_failed": 0, "status": "SUCCESS"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(_tool_call("get_load_status_today", {}))

    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=load_result) as mock_ls, \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("did all systems send data today")

    assert result["success"] is True
    assert any(t["tool"] == "get_load_status_today" for t in result["tools_called"])
    mock_ls.assert_awaited_once()
    data = result["results"][0]["result"]["data"]
    assert any(s["source_system"] == "MEDIATION" for s in data)


# ── T16-07: "systems not loaded in 3 days" → get_missing_loads(3) ─────────────

@pytest.mark.asyncio
async def test_t16_07_missing_loads_3_days():
    missing_result = {
        "success": True,
        "data": [
            {"source_system": "CDR_FEED",
             "last_load_date": "2026-06-21",
             "days_since_last_load": 3},
        ],
        "row_count": 1,
    }
    resp = _openai_response(_tool_call("get_missing_loads", {"days_back": 3}))

    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._usage.get_missing_loads",
               new_callable=AsyncMock, return_value=missing_result) as mock_ml, \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("which systems have not loaded in 3 days")

    assert result["success"] is True
    assert any(t["tool"] == "get_missing_loads" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_missing_loads")
    assert tc["args"].get("days_back", 3) == 3
    mock_ml.assert_awaited_once_with(3)
    data = result["results"][0]["result"]["data"]
    assert data[0]["source_system"] == "CDR_FEED"


# ── T16-08: "open tickets assigned to john.doe" → get_open_requests ───────────

@pytest.mark.asyncio
async def test_t16_08_open_requests_assigned_to():
    requests_result = {
        "success": True,
        "data": [
            {"request_id": 101, "request_type": "BILLING_DISPUTE",
             "priority": "HIGH", "status": "OPEN",
             "assigned_to": "john.doe"},
            {"request_id": 102, "request_type": "DATA_CORRECTION",
             "priority": "MEDIUM", "status": "IN_PROGRESS",
             "assigned_to": "john.doe"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(_tool_call("get_open_requests", {"assigned_to": "john.doe"}))

    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._usage.get_open_requests",
               new_callable=AsyncMock, return_value=requests_result) as mock_or, \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("show me open tickets assigned to john.doe")

    assert result["success"] is True
    assert any(t["tool"] == "get_open_requests" for t in result["tools_called"])
    tc = next(t for t in result["tools_called"] if t["tool"] == "get_open_requests")
    assert tc["args"].get("assigned_to") == "john.doe"
    mock_or.assert_awaited_once_with("john.doe")
    data = result["results"][0]["result"]["data"]
    assert all(r["assigned_to"] == "john.doe" for r in data)


# ── T16-09: "accounts pending termination this week" → get_accounts_pending_termination(7) ─

@pytest.mark.asyncio
async def test_t16_09_accounts_pending_termination():
    termination_result = {
        "success": True,
        "data": [
            {"account_number": "ACC-099", "customer_number": "CUST-050",
             "termination_date": "2026-06-28", "days_until_termination": 4},
        ],
        "row_count": 1,
    }
    resp = _openai_response(
        _tool_call("get_accounts_pending_termination", {"days_ahead": 7})
    )

    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._account.get_accounts_pending_termination",
               new_callable=AsyncMock, return_value=termination_result) as mock_pt, \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("which accounts are pending termination this week")

    assert result["success"] is True
    assert any(t["tool"] == "get_accounts_pending_termination"
               for t in result["tools_called"])
    tc = next(t for t in result["tools_called"]
              if t["tool"] == "get_accounts_pending_termination")
    assert tc["args"].get("days_ahead", 7) == 7
    mock_pt.assert_awaited_once_with(7)


# ── T16-10: "data quality issues today" → get_failed_load_summary + get_accounts_no_events ─

@pytest.mark.asyncio
async def test_t16_10_data_quality_issues_today():
    failed_loads_result = {
        "success": True,
        "data": [
            {"source_system": "MEDIATION", "failed_loads": 2,
             "total_records_failed": 45, "error_samples": "Timeout | ORA-12345"},
        ],
        "row_count": 1,
    }
    no_events_result = {
        "success": True,
        "data": [
            {"account_number": "ACC-033", "customer_number": "CUST-010",
             "status": "ACTIVE"},
            {"account_number": "ACC-077", "customer_number": "CUST-022",
             "status": "ACTIVE"},
        ],
        "row_count": 2,
    }
    resp = _openai_response(
        _tool_call("get_failed_load_summary", {"days_back": 1}),
        _tool_call("get_accounts_no_events", {}),
    )

    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._usage.get_failed_load_summary",
               new_callable=AsyncMock, return_value=failed_loads_result) as mock_fls, \
         patch(f"{_OPS_MODULE}._power.get_accounts_no_events",
               new_callable=AsyncMock, return_value=no_events_result) as mock_ane, \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("show me data quality issues today")

    assert result["success"] is True
    assert result["row_count"] == 2
    tool_names = [t["tool"] for t in result["tools_called"]]
    assert "get_failed_load_summary" in tool_names
    assert "get_accounts_no_events" in tool_names
    mock_fls.assert_awaited_once()
    mock_ane.assert_awaited_once()


# ── Audit log tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t16_usage_agent_audit_tool_name():
    top_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    resp = _openai_response(_tool_call("get_top_usage_accounts", {"limit": 5}))
    with _patch_openai(_USAGE_MODULE, resp), \
         patch(f"{_USAGE_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=top_result), \
         patch(f"{_USAGE_MODULE}.log_audit", audit_mock):
        from src.agents.usage_read_agent import run
        await run("top 5 accounts by usage")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "usage_read_agent"


@pytest.mark.asyncio
async def test_t16_ops_agent_audit_tool_name():
    load_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    resp = _openai_response(_tool_call("get_load_status_today", {}))
    with _patch_openai(_OPS_MODULE, resp), \
         patch(f"{_OPS_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=load_result), \
         patch(f"{_OPS_MODULE}.log_audit", audit_mock):
        from src.agents.operations_read_agent import run
        await run("load status today")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "operations_read_agent"


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t16_usage_agent_openai_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("connection timeout"))

    with patch(f"{_USAGE_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_USAGE_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.usage_read_agent import run
        result = await run("top accounts by usage")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"
    assert "timeout" in result["message"]


@pytest.mark.asyncio
async def test_t16_ops_agent_openai_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("rate limit exceeded"))

    with patch(f"{_OPS_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_OPS_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.operations_read_agent import run
        result = await run("load status today")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── Integration tests (hit real Oracle DB + real OpenAI API) ──────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_01_integration_events_by_account(db_conn):
    from src.agents.usage_read_agent import run
    result = await run("show me usage events for ACC-001 this month")
    assert result["success"] is True
    assert any(t["tool"] == "get_events_by_account" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_02_integration_top_usage_accounts(db_conn):
    from src.agents.usage_read_agent import run
    result = await run("show me the top 10 accounts by bandwidth usage")
    assert result["success"] is True
    assert any(t["tool"] == "get_top_usage_accounts" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_03_integration_usage_anomalies(db_conn):
    from src.agents.usage_read_agent import run
    result = await run("which accounts are exceeding 100 Mbps")
    assert result["success"] is True
    assert any(t["tool"] == "get_usage_anomalies" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_05_integration_bandwidth_trend(db_conn):
    from src.agents.usage_read_agent import run
    result = await run("show me the daily bandwidth trend for ACC-001")
    assert result["success"] is True
    assert any(t["tool"] == "get_bandwidth_trend" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_06_integration_load_status_today(db_conn):
    from src.agents.operations_read_agent import run
    result = await run("did all source systems send data today")
    assert result["success"] is True
    assert any(t["tool"] == "get_load_status_today" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_07_integration_missing_loads(db_conn):
    from src.agents.operations_read_agent import run
    result = await run("which systems have not loaded data in the last 3 days")
    assert result["success"] is True
    assert any(t["tool"] == "get_missing_loads" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_08_integration_open_requests(db_conn):
    from src.agents.operations_read_agent import run
    result = await run("show me open support tickets assigned to john.doe")
    assert result["success"] is True
    assert any(t["tool"] == "get_open_requests" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_09_integration_accounts_pending_termination(db_conn):
    from src.agents.operations_read_agent import run
    result = await run("which accounts are pending termination this week")
    assert result["success"] is True
    assert any(t["tool"] == "get_accounts_pending_termination"
               for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t16_10_integration_audit_logs(db_conn):
    from src.agents.usage_read_agent import run as usage_run
    from src.agents.operations_read_agent import run as ops_run
    from src.tools.approval import get_audit_log

    await usage_run("top 5 accounts by usage")
    await ops_run("load status today")

    usage_log = await get_audit_log(tool_name="usage_read_agent", limit=5)
    assert usage_log["success"] is True
    assert usage_log["row_count"] >= 1
    assert all(r["tool_name"] == "usage_read_agent" for r in usage_log["data"])

    ops_log = await get_audit_log(tool_name="operations_read_agent", limit=5)
    assert ops_log["success"] is True
    assert ops_log["row_count"] >= 1
    assert all(r["tool_name"] == "operations_read_agent" for r in ops_log["data"])
