"""
TASK 19 — read_master_agent
Unit tests: T19-01 through T19-12

All unit tests mock OpenAI (routing decision) and each sub-agent's run().
Integration tests hit real Oracle DB + real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_MODULE = "src.agents.read_master_agent"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _tool_call(name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_route_response(tool_name: str, args: dict) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = [_tool_call(tool_name, args)]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(tool_name: str, args: dict):
    response = _openai_route_response(tool_name, args)
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    return patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client)


def _sub_agent_result(agent_name: str) -> dict:
    return {"success": True, "agent": agent_name, "data": []}


# ── T19-01: routes to schema_agent ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_01_routes_to_schema_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("schema_agent"))

    with _patch_openai("schema_agent", {"question": "what tables exist?"}), \
         patch(f"{_MODULE}.schema_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("what tables exist?")

    assert result["success"] is True
    assert result["routed_to"] == "schema_agent"
    assert result["result"]["agent"] == "schema_agent"
    mock_run.assert_awaited_once_with("what tables exist?")


# ── T19-02: routes to customer_read_agent ─────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_02_routes_to_customer_read_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("customer_read_agent"))

    with _patch_openai("customer_read_agent", {"question": "show me ACME Corp customers"}), \
         patch(f"{_MODULE}.customer_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("show me ACME Corp customers")

    assert result["routed_to"] == "customer_read_agent"
    mock_run.assert_awaited_once_with("show me ACME Corp customers")


# ── T19-03: routes to billing_read_agent ──────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_03_routes_to_billing_read_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("billing_read_agent"))

    with _patch_openai("billing_read_agent", {"question": "show unpaid invoices"}), \
         patch(f"{_MODULE}.billing_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("show unpaid invoices")

    assert result["routed_to"] == "billing_read_agent"
    mock_run.assert_awaited_once_with("show unpaid invoices")


# ── T19-04: routes to usage_read_agent ────────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_04_routes_to_usage_read_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("usage_read_agent"))

    with _patch_openai("usage_read_agent", {"question": "what are the top usage accounts?"}), \
         patch(f"{_MODULE}.usage_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("what are the top usage accounts?")

    assert result["routed_to"] == "usage_read_agent"
    mock_run.assert_awaited_once_with("what are the top usage accounts?")


# ── T19-05: routes to operations_read_agent ───────────────────────────────────

@pytest.mark.asyncio
async def test_t19_05_routes_to_operations_read_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("operations_read_agent"))

    with _patch_openai("operations_read_agent",
                       {"question": "what failed to load today?"}), \
         patch(f"{_MODULE}.operations_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("what failed to load today?")

    assert result["routed_to"] == "operations_read_agent"
    mock_run.assert_awaited_once_with("what failed to load today?")


# ── T19-06: routes to rca_agent (uses customer_number, not question) ──────────

@pytest.mark.asyncio
async def test_t19_06_routes_to_rca_agent_with_customer_number():
    mock_run = AsyncMock(return_value={"success": True, "customer_number": "CUST-007",
                                       "rca_summary": "all good", "recommended_actions": []})

    with _patch_openai("rca_agent", {"customer_number": "CUST-007"}), \
         patch(f"{_MODULE}.rca_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("diagnose billing issues for CUST-007")

    assert result["routed_to"] == "rca_agent"
    # rca_agent.run called with customer_number positional arg
    mock_run.assert_awaited_once_with("CUST-007")


# ── T19-07: routes to insight_agent ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_07_routes_to_insight_agent():
    mock_run = AsyncMock(return_value=_sub_agent_result("insight_agent"))

    with _patch_openai("insight_agent",
                       {"question": "what was revenue in Q1 2026?"}), \
         patch(f"{_MODULE}.insight_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("what was revenue in Q1 2026?")

    assert result["routed_to"] == "insight_agent"
    mock_run.assert_awaited_once_with("what was revenue in Q1 2026?")


# ── T19-08: result shape contains required keys ───────────────────────────────

@pytest.mark.asyncio
async def test_t19_08_result_shape():
    mock_run = AsyncMock(return_value=_sub_agent_result("schema_agent"))

    with _patch_openai("schema_agent", {"question": "list all procedures"}), \
         patch(f"{_MODULE}.schema_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("list all procedures")

    required = {"success", "question", "routed_to", "result"}
    assert required.issubset(result.keys())
    assert result["question"] == "list all procedures"


# ── T19-09: OpenAI failure → error dict returned ──────────────────────────────

@pytest.mark.asyncio
async def test_t19_09_openai_failure_returns_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("OpenAI unavailable"))

    with patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("any question")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T19-10: audit tool_name='read_master_agent' ───────────────────────────────

@pytest.mark.asyncio
async def test_t19_10_audit_tool_name_is_read_master_agent():
    audit_mock = AsyncMock(return_value=True)
    mock_run = AsyncMock(return_value=_sub_agent_result("billing_read_agent"))

    with _patch_openai("billing_read_agent", {"question": "show bills"}), \
         patch(f"{_MODULE}.billing_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.read_master_agent import run
        await run("show bills")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "read_master_agent"


# ── T19-11: audit payload contains routed_to ─────────────────────────────────

@pytest.mark.asyncio
async def test_t19_11_audit_payload_contains_routed_to():
    audit_mock = AsyncMock(return_value=True)
    mock_run = AsyncMock(return_value=_sub_agent_result("usage_read_agent"))

    with _patch_openai("usage_read_agent", {"question": "bandwidth trends"}), \
         patch(f"{_MODULE}.usage_read_agent.run", mock_run), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.read_master_agent import run
        await run("bandwidth trends")

    payload = audit_mock.call_args[0][4]
    assert payload["routed_to"] == "usage_read_agent"


# ── T19-12: no tool_calls in response → NO_TOOL_CALLED ───────────────────────

@pytest.mark.asyncio
async def test_t19_12_no_tool_calls_returns_error():
    msg = MagicMock()
    msg.tool_calls = []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)

    with patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.read_master_agent import run
        result = await run("some question")

    assert result["success"] is False
    assert result["error_code"] == "NO_TOOL_CALLED"


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t19_01_integration_schema_routing(db_conn):
    from src.agents.read_master_agent import run
    result = await run("what packages are in the database?")
    assert result["success"] is True
    assert result["routed_to"] == "schema_agent"
    assert "result" in result


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t19_02_integration_customer_routing(db_conn):
    from src.agents.read_master_agent import run
    result = await run("show me active customers")
    assert result["success"] is True
    assert result["routed_to"] == "customer_read_agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t19_03_integration_billing_routing(db_conn):
    from src.agents.read_master_agent import run
    result = await run("show me unpaid bills")
    assert result["success"] is True
    assert result["routed_to"] == "billing_read_agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t19_07_integration_insight_routing(db_conn):
    from src.agents.read_master_agent import run
    result = await run("give me an executive revenue summary for Q1 2026")
    assert result["success"] is True
    assert result["routed_to"] == "insight_agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t19_10_integration_audit_log(db_conn):
    from src.agents.read_master_agent import run
    from src.tools.approval import get_audit_log
    await run("list all database tables")
    log = await get_audit_log(tool_name="read_master_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "read_master_agent" for r in log["data"])
