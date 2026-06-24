"""
TASK 17 — rca_agent
Unit tests: T17-01 through T17-11

All unit tests mock the Oracle tool functions and OpenAI client.
Integration tests hit the real Oracle DB and OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_MODULE = "src.agents.rca_agent"


# ── Shared mock data ──────────────────────────────────────────────────────────

def _profile_360(customer_number: str = "CUST-1042") -> dict:
    return {
        "success": True,
        "data": {
            "customer": {
                "customer_number": customer_number,
                "customer_name": "Acme Corp",
                "status": "ACTIVE",
            },
            "accounts": [{"account_number": "ACC-001"}, {"account_number": "ACC-002"}],
            "contacts": [],
            "addresses": [],
            "products": [],
            "latest_bill": None,
        },
        "row_count": 1,
    }


def _accounts_result(account_numbers: list[str]) -> dict:
    return {
        "success": True,
        "data": [{"account_number": a} for a in account_numbers],
        "row_count": len(account_numbers),
    }


def _bills_result(unpaid: bool = False) -> dict:
    if unpaid:
        return {
            "success": True,
            "data": [{"invoice_number": "INV-001", "total_amount": 1500.0,
                      "bill_status": "UNPAID"}],
            "row_count": 1,
        }
    return {"success": True, "data": [{"invoice_number": "INV-002",
                                        "total_amount": 800.0,
                                        "bill_status": "PAID"}], "row_count": 1}


def _event_summary_result(event_count: int = 10, avg_speed: float = 50.0) -> dict:
    return {
        "success": True,
        "data": {
            "event_count": event_count,
            "avg_speed_mbps": avg_speed,
            "total_in_bits": 1000000,
            "total_out_bits": 500000,
        },
        "row_count": 1,
    }


def _failed_events_result() -> dict:
    return {
        "success": True,
        "data": [{"event_id": 99, "source_system": "MEDIATION", "status": "FAILED"}],
        "row_count": 1,
    }


def _load_status_result() -> dict:
    return {
        "success": True,
        "data": [{"source_system": "MEDIATION", "status": "SUCCESS"}],
        "row_count": 1,
    }


def _health_result(customer_number: str = "CUST-1042") -> dict:
    return {
        "success": True,
        "data": {
            "customer_number": customer_number,
            "missing_address": False,
            "missing_contact": False,
            "no_active_products": False,
            "has_unpaid_bills": True,
            "unpaid_bill_count": 1,
            "unpaid_amount": 1500.0,
            "no_events_this_month": False,
        },
    }


def _openai_rca_response(summary: str = "Root cause identified.",
                          actions: list[str] | None = None) -> MagicMock:
    """Build a fake OpenAI ChatCompletion response returning valid RCA JSON."""
    actions = actions or ["Contact billing team", "Review usage data"]
    content = json.dumps({"rca_summary": summary, "recommended_actions": actions})
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(response: MagicMock):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    return patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client)


# ── T17-01: unknown customer → NOT_FOUND, stops at step 1 ────────────────────

@pytest.mark.asyncio
async def test_t17_01_unknown_customer_stops_early():
    not_found = {"success": True, "data": None, "row_count": 0}

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=not_found) as mock_360, \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock) as mock_acc, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-UNKNOWN")

    assert result["success"] is False
    assert result["error_code"] == "NOT_FOUND"
    assert "not found" in result["message"].lower()
    mock_360.assert_awaited_once_with("CUST-UNKNOWN")
    mock_acc.assert_not_awaited()


# ── T17-02: 2 accounts, 1 has UNPAID bill → billing_issues has 1 item ─────────

@pytest.mark.asyncio
async def test_t17_02_billing_issues_collected():
    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()) as mock_360, \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001", "ACC-002"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock,
               side_effect=[_bills_result(unpaid=True), _bills_result(unpaid=False)]), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               side_effect=[_event_summary_result(), _event_summary_result()]), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["success"] is True
    assert len(result["billing_issues"]) == 1
    assert result["billing_issues"][0]["bill_status"] == "UNPAID"


# ── T17-03: account with 0 events → appears in event_anomalies ───────────────

@pytest.mark.asyncio
async def test_t17_03_event_anomaly_zero_events():
    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()) as mock_360, \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result()), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               return_value=_event_summary_result(event_count=0)), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["success"] is True
    assert len(result["event_anomalies"]) == 1
    assert result["event_anomalies"][0]["account_number"] == "ACC-001"
    assert result["event_anomalies"][0]["flag"] == "no_events"


# ── T17-04: account with high speed → appears in event_anomalies ─────────────

@pytest.mark.asyncio
async def test_t17_04_event_anomaly_high_speed():
    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock,
               return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result()), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock,
               return_value=_event_summary_result(event_count=5, avg_speed=150.0)), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["success"] is True
    anomaly = result["event_anomalies"][0]
    assert anomaly["flag"] == "high_speed"
    assert anomaly["avg_speed_mbps"] == 150.0


# ── T17-05: all 7 tools called (1 account scenario) ──────────────────────────

@pytest.mark.asyncio
async def test_t17_05_all_seven_tools_called():
    mock_360 = AsyncMock(return_value=_profile_360())
    mock_acc = AsyncMock(return_value=_accounts_result(["ACC-001"]))
    mock_bills = AsyncMock(return_value=_bills_result())
    mock_events = AsyncMock(return_value=_event_summary_result())
    mock_failed = AsyncMock(return_value=_failed_events_result())
    mock_load = AsyncMock(return_value=_load_status_result())
    mock_health = AsyncMock(return_value=_health_result())

    with patch(f"{_MODULE}._customer.get_customer_360", mock_360), \
         patch(f"{_MODULE}._account.get_accounts_by_customer", mock_acc), \
         patch(f"{_MODULE}._billing.get_bills_by_account", mock_bills), \
         patch(f"{_MODULE}._usage.get_event_summary", mock_events), \
         patch(f"{_MODULE}._usage.get_failed_events", mock_failed), \
         patch(f"{_MODULE}._usage.get_load_status_today", mock_load), \
         patch(f"{_MODULE}._power.get_customer_health_check", mock_health), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["success"] is True
    mock_360.assert_awaited_once()
    mock_acc.assert_awaited_once()
    mock_bills.assert_awaited_once()
    mock_events.assert_awaited_once()
    mock_failed.assert_awaited_once()
    mock_load.assert_awaited_once()
    mock_health.assert_awaited_once()


# ── T17-06: result includes all required keys ─────────────────────────────────

@pytest.mark.asyncio
async def test_t17_06_result_shape():
    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result()), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary_result()), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response("Bill mismatch due to missing events.",
                                             ["Re-ingest events", "Re-run billing"])), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    required_keys = {"success", "customer_number", "customer_profile",
                     "billing_issues", "event_anomalies", "health_flags",
                     "rca_summary", "recommended_actions"}
    assert required_keys.issubset(result.keys())
    assert result["rca_summary"] == "Bill mismatch due to missing events."
    assert "Re-ingest events" in result["recommended_actions"]


# ── T17-07: GPT-4o returns valid JSON → rca_summary and recommended_actions ───

@pytest.mark.asyncio
async def test_t17_07_gpt_json_parsed_correctly():
    summary = "Root cause: missing events from MEDIATION system."
    actions = ["Contact MEDIATION team", "Re-ingest failed events", "Re-run billing"]

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result()), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary_result()), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response(summary, actions)), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["rca_summary"] == summary
    assert result["recommended_actions"] == actions


# ── T17-08: GPT-4o failure → success=True, rca_summary="AI summary unavailable"

@pytest.mark.asyncio
async def test_t17_08_gpt_failure_returns_partial_data():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("OpenAI API rate limit"))

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result(unpaid=True)), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary_result()), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    # Data collection succeeded; only synthesis failed
    assert result["success"] is True
    assert result["rca_summary"] == "AI summary unavailable"
    assert result["recommended_actions"] == []
    # Billing data was still collected
    assert len(result["billing_issues"]) == 1


# ── T17-09: audit log shows tool_name='rca_agent' ────────────────────────────

@pytest.mark.asyncio
async def test_t17_09_audit_tool_name_is_rca_agent():
    audit_mock = AsyncMock(return_value=True)

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result(["ACC-001"])), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock, return_value=_bills_result()), \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock, return_value=_event_summary_result()), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.rca_agent import run
        await run("CUST-1042")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "rca_agent"
    # tools_used should be in the payload
    payload = audit_mock.call_args[0][4]
    assert "tools_used" in payload
    assert len(payload["tools_used"]) == 7


# ── T17-10: GPT-4o failure audit still uses SUCCESS (data collected) ──────────

@pytest.mark.asyncio
async def test_t17_10_audit_status_success_even_on_gpt_failure():
    audit_mock = AsyncMock(return_value=True)
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result([])), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.rca_agent import run
        await run("CUST-1042")

    assert audit_mock.call_args[0][5] == "SUCCESS"


# ── T17-11: customer with no accounts → no bills or event calls ───────────────

@pytest.mark.asyncio
async def test_t17_11_customer_with_no_accounts():
    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock,
               return_value={"success": True, "data": [], "row_count": 0}), \
         patch(f"{_MODULE}._billing.get_bills_by_account",
               new_callable=AsyncMock) as mock_bills, \
         patch(f"{_MODULE}._usage.get_event_summary",
               new_callable=AsyncMock) as mock_events, \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         _patch_openai(_openai_rca_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["success"] is True
    assert result["billing_issues"] == []
    assert result["event_anomalies"] == []
    mock_bills.assert_not_awaited()
    mock_events.assert_not_awaited()


# ── T17: markdown-fenced JSON from GPT-4o is handled ─────────────────────────

@pytest.mark.asyncio
async def test_t17_gpt_markdown_fenced_json_handled():
    """GPT-4o sometimes wraps JSON in ```json fences — must still parse."""
    fenced_content = '```json\n{"rca_summary": "Fence test.", "recommended_actions": ["action1"]}\n```'
    msg = MagicMock()
    msg.content = fenced_content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)

    with patch(f"{_MODULE}._customer.get_customer_360",
               new_callable=AsyncMock, return_value=_profile_360()), \
         patch(f"{_MODULE}._account.get_accounts_by_customer",
               new_callable=AsyncMock, return_value=_accounts_result([])), \
         patch(f"{_MODULE}._usage.get_failed_events",
               new_callable=AsyncMock, return_value=_failed_events_result()), \
         patch(f"{_MODULE}._usage.get_load_status_today",
               new_callable=AsyncMock, return_value=_load_status_result()), \
         patch(f"{_MODULE}._power.get_customer_health_check",
               new_callable=AsyncMock, return_value=_health_result()), \
         patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.rca_agent import run
        result = await run("CUST-1042")

    assert result["rca_summary"] == "Fence test."
    assert result["recommended_actions"] == ["action1"]


# ── Integration tests (hit real Oracle DB + real OpenAI API) ──────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t17_01_integration_unknown_customer(db_conn):
    from src.agents.rca_agent import run
    result = await run("CUST-DOES-NOT-EXIST-99999")
    assert result["success"] is False
    assert result["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t17_02_integration_rca_full_flow(db_conn):
    from src.agents.rca_agent import run
    result = await run("CUST-001")
    assert result["success"] is True
    assert "customer_profile" in result
    assert isinstance(result["billing_issues"], list)
    assert isinstance(result["event_anomalies"], list)
    assert "health_flags" in result
    assert isinstance(result["recommended_actions"], list)
    assert result["rca_summary"] != ""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t17_07_integration_audit_log(db_conn):
    from src.agents.rca_agent import run
    from src.tools.approval import get_audit_log
    await run("CUST-001")
    log = await get_audit_log(tool_name="rca_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "rca_agent" for r in log["data"])
