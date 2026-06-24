"""
TASK 23 — write_master_agent + intent_router
Unit tests: T23-01 through T23-20

All unit tests mock OpenAI (routing) and each sub-agent's run().
Integration tests hit real Oracle DB + real OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_WM_MODULE = "src.agents.write_master_agent"
_IR_MODULE  = "src.agents.intent_router"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _tool_call(name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_response(tool_name: str, args: dict) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = [_tool_call(tool_name, args)]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(module: str, tool_name: str, args: dict):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response(tool_name, args))
    return patch(f"{module}.AsyncOpenAI", return_value=mock_client)


def _sub_result(name: str) -> dict:
    return {"success": True, "agent": name, "data": []}


_ONBOARDING_ARGS = {
    "customer_name": "ACME Ltd", "company_code": "ACME",
    "customer_type_code": "CORP", "address_type": "BILLING",
    "address_line1": "1 Main St", "city": "Mumbai", "country": "IN",
    "contact_name": "Alice", "designation": "CEO", "email": "alice@acme.com",
    "account_name": "ACME Main", "currency_code": "USD", "product_code": "MPLS-1G",
}


# ═══════════════════════════════════════════════════════════════════════════════
# write_master_agent tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── T23-01: routes to onboarding_agent (args passed as dict) ──────────────────

@pytest.mark.asyncio
async def test_t23_01_routes_to_onboarding_agent():
    mock_run = AsyncMock(return_value={
        "success": True, "steps_completed": 5, "customer_number": "CUST-000001"
    })

    with _patch_openai(_WM_MODULE, "onboarding_agent", _ONBOARDING_ARGS), \
         patch(f"{_WM_MODULE}.onboarding_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("onboard a new customer ACME Ltd")

    assert result["success"] is True
    assert result["routed_to"] == "onboarding_agent"
    # onboarding_agent.run called with the full args dict
    mock_run.assert_awaited_once_with(_ONBOARDING_ARGS)


# ── T23-02: routes to billing_run_agent (billing_month + requested_by) ────────

@pytest.mark.asyncio
async def test_t23_02_routes_to_billing_run_agent():
    mock_run = AsyncMock(return_value={
        "success": True, "billing_month": "2026-06",
        "queued": 5, "approval_ids": [1, 2, 3, 4, 5]
    })
    args = {"billing_month": "2026-06", "requested_by": "billing_user"}

    with _patch_openai(_WM_MODULE, "billing_run_agent", args), \
         patch(f"{_WM_MODULE}.billing_run_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("run billing for June 2026")

    assert result["routed_to"] == "billing_run_agent"
    mock_run.assert_awaited_once_with("2026-06", "billing_user")


# ── T23-02b: billing_run_agent requested_by defaults to mcp_user ─────────────

@pytest.mark.asyncio
async def test_t23_02b_billing_run_default_requested_by():
    mock_run = AsyncMock(return_value={"success": True, "queued": 0})
    args = {"billing_month": "2026-07"}  # no requested_by

    with _patch_openai(_WM_MODULE, "billing_run_agent", args), \
         patch(f"{_WM_MODULE}.billing_run_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        await run("run July billing")

    mock_run.assert_awaited_once_with("2026-07", "mcp_user")


# ── T23-03: routes to dml_agent (question passed) ────────────────────────────

@pytest.mark.asyncio
async def test_t23_03_routes_to_dml_agent():
    mock_run = AsyncMock(return_value=_sub_result("dml_agent"))
    args = {"question": "create customer ACME Corp"}

    with _patch_openai(_WM_MODULE, "dml_agent", args), \
         patch(f"{_WM_MODULE}.dml_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("create customer ACME Corp")

    assert result["routed_to"] == "dml_agent"
    mock_run.assert_awaited_once_with("create customer ACME Corp")


# ── T23-04: routes to approval_agent ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_04_routes_to_approval_agent():
    mock_run = AsyncMock(return_value=_sub_result("approval_agent"))
    args = {"question": "approve request 42"}

    with _patch_openai(_WM_MODULE, "approval_agent", args), \
         patch(f"{_WM_MODULE}.approval_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("approve request 42")

    assert result["routed_to"] == "approval_agent"
    mock_run.assert_awaited_once_with("approve request 42")


# ── T23-05: routes to adjustment_agent ───────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_05_routes_to_adjustment_agent():
    mock_run = AsyncMock(return_value=_sub_result("adjustment_agent"))
    args = {"question": "apply $500 credit to INV-001"}

    with _patch_openai(_WM_MODULE, "adjustment_agent", args), \
         patch(f"{_WM_MODULE}.adjustment_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("apply $500 credit to INV-001")

    assert result["routed_to"] == "adjustment_agent"
    mock_run.assert_awaited_once_with("apply $500 credit to INV-001")


# ── T23-06: result shape ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_06_result_shape():
    mock_run = AsyncMock(return_value=_sub_result("dml_agent"))

    with _patch_openai(_WM_MODULE, "dml_agent", {"question": "create customer"}), \
         patch(f"{_WM_MODULE}.dml_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("create customer")

    required = {"success", "question", "routed_to", "result"}
    assert required.issubset(result.keys())
    assert result["question"] == "create customer"


# ── T23-07: OpenAI failure → OPENAI_ERROR ────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_07_openai_failure():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    with patch(f"{_WM_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("create a customer")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T23-08: audit tool_name='write_master_agent', action_type='WRITE' ─────────

@pytest.mark.asyncio
async def test_t23_08_audit_tool_name_write_master():
    audit_mock = AsyncMock(return_value=True)
    mock_run = AsyncMock(return_value=_sub_result("dml_agent"))

    with _patch_openai(_WM_MODULE, "dml_agent", {"question": "create customer"}), \
         patch(f"{_WM_MODULE}.dml_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", audit_mock):
        from src.agents.write_master_agent import run
        await run("create customer")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "write_master_agent"
    assert audit_mock.call_args[0][3] == "WRITE"


# ── T23-09: audit payload contains routed_to ─────────────────────────────────

@pytest.mark.asyncio
async def test_t23_09_audit_payload_routed_to():
    audit_mock = AsyncMock(return_value=True)
    mock_run = AsyncMock(return_value=_sub_result("approval_agent"))

    with _patch_openai(_WM_MODULE, "approval_agent", {"question": "list approvals"}), \
         patch(f"{_WM_MODULE}.approval_agent.run", mock_run), \
         patch(f"{_WM_MODULE}.log_audit", audit_mock):
        from src.agents.write_master_agent import run
        await run("list approvals")

    payload = audit_mock.call_args[0][4]
    assert payload["routed_to"] == "approval_agent"


# ── T23-10: no tool_calls → NO_TOOL_CALLED ────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_10_no_tool_calls_returns_error():
    msg = MagicMock()
    msg.tool_calls = []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)

    with patch(f"{_WM_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_WM_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.write_master_agent import run
        result = await run("some write request")

    assert result["success"] is False
    assert result["error_code"] == "NO_TOOL_CALLED"


# ═══════════════════════════════════════════════════════════════════════════════
# intent_router tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── T23-11: READ question → route_to_read_master → read_master_agent ──────────

@pytest.mark.asyncio
async def test_t23_11_read_question_routes_to_read_master():
    mock_read = AsyncMock(return_value={"success": True, "routed_to": "billing_read_agent",
                                        "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_read_master",
                       {"question": "show me unpaid bills"}), \
         patch(f"{_IR_MODULE}.read_master_agent.run", mock_read), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("show me unpaid bills")

    assert result["success"] is True
    assert result["intent"] == "READ"
    assert result["routed_to"] == "read_master_agent"
    mock_read.assert_awaited_once_with("show me unpaid bills")


# ── T23-12: WRITE question → route_to_write_master → write_master_agent ───────

@pytest.mark.asyncio
async def test_t23_12_write_question_routes_to_write_master():
    mock_write = AsyncMock(return_value={"success": True, "routed_to": "dml_agent",
                                          "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_write_master",
                       {"question": "create a new customer"}), \
         patch(f"{_IR_MODULE}.write_master_agent.run", mock_write), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("create a new customer")

    assert result["intent"] == "WRITE"
    assert result["routed_to"] == "write_master_agent"
    mock_write.assert_awaited_once_with("create a new customer")


# ── T23-13: intent="READ" for schema discovery ────────────────────────────────

@pytest.mark.asyncio
async def test_t23_13_schema_query_is_read():
    mock_read = AsyncMock(return_value={"success": True, "routed_to": "schema_agent",
                                        "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_read_master",
                       {"question": "what tables exist?"}), \
         patch(f"{_IR_MODULE}.read_master_agent.run", mock_read), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("what tables exist?")

    assert result["intent"] == "READ"


# ── T23-14: intent="WRITE" for billing run ────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_14_billing_run_is_write():
    mock_write = AsyncMock(return_value={"success": True, "routed_to": "billing_run_agent",
                                          "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_write_master",
                       {"question": "run billing for June 2026"}), \
         patch(f"{_IR_MODULE}.write_master_agent.run", mock_write), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("run billing for June 2026")

    assert result["intent"] == "WRITE"


# ── T23-15: intent="WRITE" for onboarding ────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_15_onboarding_is_write():
    mock_write = AsyncMock(return_value={"success": True, "routed_to": "onboarding_agent",
                                          "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_write_master",
                       {"question": "onboard a new customer"}), \
         patch(f"{_IR_MODULE}.write_master_agent.run", mock_write), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("onboard a new customer")

    assert result["intent"] == "WRITE"


# ── T23-16: result shape ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_16_result_shape():
    mock_read = AsyncMock(return_value={"success": True, "routed_to": "insight_agent",
                                        "result": {}})

    with _patch_openai(_IR_MODULE, "route_to_read_master",
                       {"question": "revenue summary"}), \
         patch(f"{_IR_MODULE}.read_master_agent.run", mock_read), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("revenue summary")

    required = {"success", "question", "intent", "routed_to", "result"}
    assert required.issubset(result.keys())
    assert result["question"] == "revenue summary"


# ── T23-17: audit tool_name='intent_router' ───────────────────────────────────

@pytest.mark.asyncio
async def test_t23_17_audit_tool_name_intent_router():
    audit_mock = AsyncMock(return_value=True)
    mock_read = AsyncMock(return_value={"success": True})

    with _patch_openai(_IR_MODULE, "route_to_read_master",
                       {"question": "list customers"}), \
         patch(f"{_IR_MODULE}.read_master_agent.run", mock_read), \
         patch(f"{_IR_MODULE}.log_audit", audit_mock):
        from src.agents.intent_router import run
        await run("list customers")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "intent_router"


# ── T23-18: audit payload contains intent and routed_to ──────────────────────

@pytest.mark.asyncio
async def test_t23_18_audit_payload_contains_intent_and_routed_to():
    audit_mock = AsyncMock(return_value=True)
    mock_write = AsyncMock(return_value={"success": True})

    with _patch_openai(_IR_MODULE, "route_to_write_master",
                       {"question": "approve request 5"}), \
         patch(f"{_IR_MODULE}.write_master_agent.run", mock_write), \
         patch(f"{_IR_MODULE}.log_audit", audit_mock):
        from src.agents.intent_router import run
        await run("approve request 5")

    payload = audit_mock.call_args[0][4]
    assert payload["intent"] == "WRITE"
    assert payload["routed_to"] == "write_master_agent"


# ── T23-19: OpenAI failure → OPENAI_ERROR ────────────────────────────────────

@pytest.mark.asyncio
async def test_t23_19_intent_router_openai_failure():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))

    with patch(f"{_IR_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_IR_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.intent_router import run
        result = await run("do something")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"


# ── T23-20: READ audit action_type is "READ", WRITE is "WRITE" ───────────────

@pytest.mark.asyncio
async def test_t23_20_read_audit_action_type():
    audit_mock = AsyncMock(return_value=True)
    mock_read = AsyncMock(return_value={"success": True})

    with _patch_openai(_IR_MODULE, "route_to_read_master",
                       {"question": "show active customers"}), \
         patch(f"{_IR_MODULE}.read_master_agent.run", mock_read), \
         patch(f"{_IR_MODULE}.log_audit", audit_mock):
        from src.agents.intent_router import run
        await run("show active customers")

    assert audit_mock.call_args[0][3] == "READ"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t23_01_integration_write_master_dml(db_conn):
    from src.agents.write_master_agent import run
    result = await run("create a new currency with code ZZZ and name Zeta Currency")
    assert result["success"] is True
    assert result["routed_to"] in ("dml_agent", "onboarding_agent",
                                   "billing_run_agent", "approval_agent",
                                   "adjustment_agent")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t23_11_integration_intent_router_read(db_conn):
    from src.agents.intent_router import run
    result = await run("show me all active customers")
    assert result["success"] is True
    assert result["intent"] == "READ"
    assert result["routed_to"] == "read_master_agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t23_12_integration_intent_router_write(db_conn):
    from src.agents.intent_router import run
    result = await run("create a new customer called TestCorp with company TCORP")
    assert result["success"] is True
    assert result["intent"] == "WRITE"
    assert result["routed_to"] == "write_master_agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t23_17_integration_audit_log(db_conn):
    from src.agents.intent_router import run
    from src.tools.approval import get_audit_log
    await run("list all database packages")
    log = await get_audit_log(tool_name="intent_router", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "intent_router" for r in log["data"])
