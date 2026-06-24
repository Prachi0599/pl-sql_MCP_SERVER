"""
TASK 14 — schema_agent
Unit tests: T14-01 through T14-07

All unit tests mock the OpenAI client so no real API calls are made.
Integration tests hit both the real Oracle DB and the real OpenAI API.
"""
import json
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch, call

_MODULE = "src.agents.schema_agent"


# ── OpenAI response mock helpers ──────────────────────────────────────────────

def _tool_call(name: str, args: dict) -> MagicMock:
    """Build a single fake tool_call object matching openai.types.chat.ChatCompletionMessageToolCall."""
    tc = MagicMock()
    tc.id = f"call_{name}"
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _openai_response(*tool_calls) -> MagicMock:
    """Wrap tool_calls in a fake OpenAI ChatCompletion response."""
    msg = MagicMock()
    msg.tool_calls = list(tool_calls)
    msg.content = None

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_openai(response: MagicMock):
    """Return a context manager that patches AsyncOpenAI and returns the fake response."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    return patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client)


def _patch_schema_tool(tool_name: str, return_value):
    """Patch a schema tool inside the schema_agent module."""
    return patch(f"{_MODULE}._schema.{tool_name}",
                 new_callable=AsyncMock, return_value=return_value)


# ── T14-01: "list all packages" → calls list_packages → returns 9 ─────────────

@pytest.mark.asyncio
async def test_t14_01_list_packages_called():
    nine_packages = [{"package_name": f"PKG_{i}"} for i in range(9)]
    packages_result = {"success": True, "data": nine_packages, "row_count": 9}

    resp = _openai_response(_tool_call("list_packages", {}))
    with _patch_openai(resp), \
         _patch_schema_tool("list_packages", packages_result) as mock_lp, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("list all packages")

    assert result["success"] is True
    assert any(t["tool"] == "list_packages" for t in result["tools_called"])
    mock_lp.assert_awaited_once()
    assert result["results"][0]["result"]["row_count"] == 9


# ── T14-02: "what does BILLING_PKG contain" → calls list_package_procedures ──

@pytest.mark.asyncio
async def test_t14_02_list_package_procedures_called():
    procs_result = {
        "success": True,
        "data": [
            {"procedure_name": "GENERATE_BILL"},
            {"procedure_name": "UPDATE_BILL_STATUS"},
            {"procedure_name": "GET_BILL_DETAILS"},
        ],
        "row_count": 3,
    }

    resp = _openai_response(_tool_call("list_package_procedures", {"package_name": "BILLING_PKG"}))
    with _patch_openai(resp), \
         _patch_schema_tool("list_package_procedures", procs_result) as mock_lpp, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("what does BILLING_PKG contain")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "list_package_procedures"
    assert result["tools_called"][0]["args"]["package_name"] == "BILLING_PKG"
    mock_lpp.assert_awaited_once_with("BILLING_PKG")
    assert result["results"][0]["result"]["row_count"] == 3


# ── T14-03: "parameters for GENERATE_BILL" → calls get_procedure_signature ───

@pytest.mark.asyncio
async def test_t14_03_get_procedure_signature_called():
    sig_result = {
        "success": True,
        "data": [
            {"argument_name": "P_ACCOUNT_ID",  "position": 1, "data_type": "NUMBER", "in_out": "IN"},
            {"argument_name": "P_BILL_AMOUNT",  "position": 2, "data_type": "NUMBER", "in_out": "IN"},
            {"argument_name": "P_TAX_AMOUNT",   "position": 3, "data_type": "NUMBER", "in_out": "IN"},
            {"argument_name": "P_CURRENCY_ID",  "position": 4, "data_type": "NUMBER", "in_out": "IN"},
        ],
        "row_count": 4,
    }

    resp = _openai_response(_tool_call("get_procedure_signature",
                                        {"package_name": "BILLING_PKG",
                                         "procedure_name": "GENERATE_BILL"}))
    with _patch_openai(resp), \
         _patch_schema_tool("get_procedure_signature", sig_result) as mock_gps, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("what are the parameters for GENERATE_BILL")

    assert result["success"] is True
    tc = result["tools_called"][0]
    assert tc["tool"] == "get_procedure_signature"
    assert tc["args"]["package_name"] == "BILLING_PKG"
    assert tc["args"]["procedure_name"] == "GENERATE_BILL"
    mock_gps.assert_awaited_once_with("BILLING_PKG", "GENERATE_BILL")
    params = result["results"][0]["result"]["data"]
    assert any(p["argument_name"] == "P_ACCOUNT_ID" for p in params)


# ── T14-04: "which procedures touch BILL_SUMMARY" → calls find_procedure_for_table ─

@pytest.mark.asyncio
async def test_t14_04_find_procedure_for_table_called():
    find_result = {
        "success": True,
        "data": [
            {"package_name": "BILLING_PKG", "line_text": "FROM MCP_APP.BILL_SUMMARY bs"},
            {"package_name": "BILLING_PKG", "line_text": "INSERT INTO MCP_APP.BILL_SUMMARY"},
        ],
        "row_count": 2,
    }

    resp = _openai_response(_tool_call("find_procedure_for_table",
                                        {"table_name": "BILL_SUMMARY"}))
    with _patch_openai(resp), \
         _patch_schema_tool("find_procedure_for_table", find_result) as mock_fpt, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("which procedures touch BILL_SUMMARY")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "find_procedure_for_table"
    assert result["tools_called"][0]["args"]["table_name"] == "BILL_SUMMARY"
    mock_fpt.assert_awaited_once_with("BILL_SUMMARY")


# ── T14-05: "describe customer table" → calls describe_table('CUSTOMER') ─────

@pytest.mark.asyncio
async def test_t14_05_describe_table_customer_called():
    desc_result = {
        "success": True,
        "data": {
            "table_name": "CUSTOMER",
            "columns": [
                {"column_name": "CUSTOMER_ID",     "data_type": "NUMBER"},
                {"column_name": "CUSTOMER_NUMBER",  "data_type": "VARCHAR2"},
                {"column_name": "CUSTOMER_NAME",    "data_type": "VARCHAR2"},
                {"column_name": "STATUS",           "data_type": "VARCHAR2"},
                {"column_name": "START_DATE",       "data_type": "DATE"},
                {"column_name": "INV_COMPANY_ID",   "data_type": "NUMBER"},
                {"column_name": "CUSTOMER_TYPE_ID", "data_type": "NUMBER"},
            ],
            "constraints": [],
        },
    }

    resp = _openai_response(_tool_call("describe_table", {"table_name": "CUSTOMER"}))
    with _patch_openai(resp), \
         _patch_schema_tool("describe_table", desc_result) as mock_dt, \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("describe the customer table")

    assert result["success"] is True
    assert result["tools_called"][0]["tool"] == "describe_table"
    assert result["tools_called"][0]["args"]["table_name"] == "CUSTOMER"
    mock_dt.assert_awaited_once_with("CUSTOMER")
    cols = result["results"][0]["result"]["data"]["columns"]
    col_names = [c["column_name"] for c in cols]
    assert "CUSTOMER_ID" in col_names
    assert "CUSTOMER_NAME" in col_names


# ── T14-06: "how are CUSTOMER and ACCOUNT related" → FK info returned ─────────

@pytest.mark.asyncio
async def test_t14_06_fk_relationship_returned():
    """Agent calls describe_table for both tables; FK constraint surfaces in ACCOUNT."""
    customer_desc = {
        "success": True,
        "data": {
            "table_name": "CUSTOMER",
            "columns": [{"column_name": "CUSTOMER_ID", "data_type": "NUMBER"}],
            "constraints": [{"constraint_name": "SYS_C008663", "constraint_type": "P",
                             "column_name": "CUSTOMER_ID", "ref_table": None}],
        },
    }
    account_desc = {
        "success": True,
        "data": {
            "table_name": "ACCOUNT",
            "columns": [
                {"column_name": "ACCOUNT_ID",  "data_type": "NUMBER"},
                {"column_name": "CUSTOMER_ID", "data_type": "NUMBER"},
            ],
            "constraints": [
                {"constraint_name": "FK_ACCOUNT_CUSTOMER", "constraint_type": "R",
                 "column_name": "CUSTOMER_ID",
                 "r_constraint_name": "SYS_C008663", "ref_table": "CUSTOMER"},
            ],
        },
    }

    # GPT-4o calls describe_table for both tables
    resp = _openai_response(
        _tool_call("describe_table", {"table_name": "CUSTOMER"}),
        _tool_call("describe_table", {"table_name": "ACCOUNT"}),
    )

    dt_mock = AsyncMock(side_effect=[customer_desc, account_desc])
    with _patch_openai(resp), \
         patch(f"{_MODULE}._schema.describe_table", dt_mock), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("how are CUSTOMER and ACCOUNT related")

    assert result["success"] is True
    assert result["row_count"] == 2  # two tool calls → two results
    # FK constraint must appear in the ACCOUNT describe result
    account_result = result["results"][1]["result"]
    fk_constraints = [c for c in account_result["data"]["constraints"]
                      if c["constraint_type"] == "R"]
    assert len(fk_constraints) >= 1
    assert fk_constraints[0]["ref_table"] == "CUSTOMER"


# ── T14-07: audit log shows TOOL_NAME='schema_agent' for every call ───────────

@pytest.mark.asyncio
async def test_t14_07_audit_log_tool_name_is_schema_agent():
    packages_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    resp = _openai_response(_tool_call("list_packages", {}))
    with _patch_openai(resp), \
         _patch_schema_tool("list_packages", packages_result), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.schema_agent import run
        await run("list all packages")

    audit_mock.assert_awaited_once()
    # First positional argument to log_audit is tool_name
    assert audit_mock.call_args[0][0] == "schema_agent"


@pytest.mark.asyncio
async def test_t14_07b_audit_logged_on_each_call():
    """Every schema_agent call writes exactly one audit entry."""
    packages_result = {"success": True, "data": [], "row_count": 0}
    audit_mock = AsyncMock(return_value=True)

    for question in ["list all packages", "describe customer table", "list sequences"]:
        resp = _openai_response(_tool_call("list_packages", {}))
        with _patch_openai(resp), \
             _patch_schema_tool("list_packages", packages_result), \
             patch(f"{_MODULE}.log_audit", audit_mock):
            from src.agents.schema_agent import run
            await run(question)

        assert audit_mock.call_args[0][0] == "schema_agent"
        audit_mock.reset_mock()


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t14_openai_error_returns_structured_error():
    """If OpenAI API fails, returns {success:False, error_code:'OPENAI_ERROR'}."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API rate limit exceeded"))

    with patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("list all packages")

    assert result["success"] is False
    assert result["error_code"] == "OPENAI_ERROR"
    assert "rate limit" in result["message"]


@pytest.mark.asyncio
async def test_t14_multiple_tools_in_one_response():
    """Agent can handle GPT-4o selecting multiple tools in a single response."""
    packages_result = {"success": True, "data": [{"package_name": "BILLING_PKG"}], "row_count": 1}
    tables_result   = {"success": True, "data": [{"table_name": "CUSTOMER"}], "row_count": 1}

    resp = _openai_response(
        _tool_call("list_packages", {}),
        _tool_call("list_tables", {}),
    )
    with _patch_openai(resp), \
         _patch_schema_tool("list_packages", packages_result), \
         _patch_schema_tool("list_tables", tables_result), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock, return_value=True):
        from src.agents.schema_agent import run
        result = await run("give me a schema overview")

    assert result["success"] is True
    assert result["row_count"] == 2
    tool_names = [t["tool"] for t in result["tools_called"]]
    assert "list_packages" in tool_names
    assert "list_tables" in tool_names


# ── Integration tests (hit real Oracle DB + real OpenAI API) ──────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_01_integration_list_packages_returns_9(db_conn):
    from src.agents.schema_agent import run
    result = await run("list all PL/SQL packages in this schema")
    assert result["success"] is True
    assert any(t["tool"] == "list_packages" for t in result["tools_called"])
    packages_result = next(r for r in result["results"] if r["tool"] == "list_packages")
    assert packages_result["result"]["success"] is True
    assert packages_result["result"]["row_count"] == 9


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_02_integration_billing_pkg_procedures(db_conn):
    from src.agents.schema_agent import run
    result = await run("what procedures does BILLING_PKG contain?")
    assert result["success"] is True
    assert any(t["tool"] == "list_package_procedures" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_03_integration_generate_bill_signature(db_conn):
    from src.agents.schema_agent import run
    result = await run("show me the parameters for the GENERATE_BILL procedure in BILLING_PKG")
    assert result["success"] is True
    assert any(t["tool"] == "get_procedure_signature" for t in result["tools_called"])
    sig_result = next(r for r in result["results"] if r["tool"] == "get_procedure_signature")
    assert sig_result["result"]["success"] is True
    assert len(sig_result["result"]["data"]) >= 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_04_integration_find_procedures_for_bill_summary(db_conn):
    from src.agents.schema_agent import run
    result = await run("which procedures and packages reference the BILL_SUMMARY table?")
    assert result["success"] is True
    assert any(t["tool"] == "find_procedure_for_table" for t in result["tools_called"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_05_integration_describe_customer(db_conn):
    from src.agents.schema_agent import run
    result = await run("describe the CUSTOMER table structure")
    assert result["success"] is True
    assert any(t["tool"] == "describe_table" for t in result["tools_called"])
    desc = next(r for r in result["results"] if r["tool"] == "describe_table")
    data = desc["result"]["data"]
    cols = [c["column_name"] for c in data.get("columns", [])]
    assert "CUSTOMER_ID" in cols
    assert "CUSTOMER_NAME" in cols


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_06_integration_customer_account_relationship(db_conn):
    from src.agents.schema_agent import run
    result = await run("how are the CUSTOMER and ACCOUNT tables related? Show FK constraints.")
    assert result["success"] is True
    # At least one describe_table call should be made
    assert any(t["tool"] == "describe_table" for t in result["tools_called"])
    # FK constraint should appear somewhere in results
    all_constraints = []
    for r in result["results"]:
        if r["tool"] == "describe_table":
            data = r["result"].get("data", {})
            all_constraints.extend(data.get("constraints", []))
    fk_constraints = [c for c in all_constraints if c.get("constraint_type") == "R"]
    assert len(fk_constraints) >= 1, "Expected FK constraint(s) in result"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t14_07_integration_audit_tool_name(db_conn):
    """After a real call, MCP_AUDIT_LOG should have a row with TOOL_NAME='schema_agent'."""
    from src.agents.schema_agent import run
    from src.tools.approval import get_audit_log

    await run("list all tables")

    log = await get_audit_log(tool_name="schema_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "schema_agent" for r in log["data"])
