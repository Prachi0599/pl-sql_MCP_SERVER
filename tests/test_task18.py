"""
TASK 18 — insight_agent
Unit tests: T18-01 through T18-08

All unit tests mock the Oracle tool functions and OpenAI client.
Integration tests hit the real Oracle DB and OpenAI API.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_MODULE = "src.agents.insight_agent"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _monthly_revenue_data() -> dict:
    return {
        "success": True,
        "data": [
            {"month": "2026-06", "total_revenue": 120000.0, "invoice_count": 40},
            {"month": "2026-05", "total_revenue": 115000.0, "invoice_count": 38},
            {"month": "2026-04", "total_revenue": 110000.0, "invoice_count": 36},
            {"month": "2026-03", "total_revenue": 105000.0, "invoice_count": 35},
            {"month": "2026-02", "total_revenue": 98000.0,  "invoice_count": 33},
            {"month": "2026-01", "total_revenue": 92000.0,  "invoice_count": 30},
        ],
        "row_count": 6,
    }


def _product_breakdown_data() -> dict:
    return {
        "success": True,
        "data": [
            {"product_type": "MPLS",  "total_revenue": 300000.0, "account_count": 25},
            {"product_type": "VOICE", "total_revenue": 140000.0, "account_count": 48},
            {"product_type": "DATA",  "total_revenue": 200000.0, "account_count": 30},
        ],
        "row_count": 3,
    }


def _top_accounts_data() -> dict:
    return {
        "success": True,
        "data": [
            {"account_number": f"ACC-{i:03d}", "avg_speed_mbps": 90.0 - i,
             "total_bits": 1000000 - i * 1000}
            for i in range(10)
        ],
        "row_count": 10,
    }


def _unpaid_bills_data() -> dict:
    return {
        "success": True,
        "data": [
            {"invoice_number": "INV-001", "total_amount": 5000.0, "bill_status": "UNPAID"},
            {"invoice_number": "INV-002", "total_amount": 3200.0, "bill_status": "OVERDUE"},
        ],
        "row_count": 2,
    }


def _openai_narrative_response(narrative: str = "Revenue is trending upward.") -> MagicMock:
    content = json.dumps({"narrative": narrative})
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


def _patch_all_tools(
    revenue=None, product=None, top=None, unpaid=None
):
    """Convenience context manager stacking all 4 tool patches."""
    import contextlib
    return contextlib.ExitStack()  # used inline below for clarity


# ── T18-01: all 4 tools called, GPT returns JSON → full result correct ─────

@pytest.mark.asyncio
async def test_t18_01_all_four_tools_called_result_correct():
    mock_rev  = AsyncMock(return_value=_monthly_revenue_data())
    mock_prod = AsyncMock(return_value=_product_breakdown_data())
    mock_top  = AsyncMock(return_value=_top_accounts_data())
    mock_unp  = AsyncMock(return_value=_unpaid_bills_data())

    with patch(f"{_MODULE}._billing.get_monthly_revenue", mock_rev), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type", mock_prod), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts", mock_top), \
         patch(f"{_MODULE}._billing.get_unpaid_bills", mock_unp), \
         _patch_openai(_openai_narrative_response("Revenue steady.")), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("give me a revenue overview")

    assert result["success"] is True
    mock_rev.assert_awaited_once_with(months=12)
    mock_prod.assert_awaited_once()
    mock_top.assert_awaited_once_with(limit=10)
    mock_unp.assert_awaited_once()

    assert isinstance(result["product_breakdown"], list)
    assert len(result["product_breakdown"]) == 3
    assert isinstance(result["top_accounts"], list)
    assert len(result["top_accounts"]) == 10
    assert isinstance(result["outstanding"], list)
    assert result["narrative"] == "Revenue steady."


# ── T18-02: "Q1 2026" → period detected, revenue_total = sum Jan+Feb+Mar ──

@pytest.mark.asyncio
async def test_t18_02_q1_period_detected_and_filtered():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response("Q1 looked strong.")), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("give me the revenue summary for Q1 2026")

    assert result["success"] is True
    assert "Q1" in result["period"]
    assert "2026" in result["period"]
    # Jan=92000 + Feb=98000 + Mar=105000 = 295000
    assert result["revenue_total"] == pytest.approx(295000.0)


# ── T18-02b: "Q2 2026" → Apr+May+Jun ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_t18_02b_q2_period_detected_and_filtered():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("show Q2 2026 revenue")

    assert "Q2" in result["period"]
    # Apr=110000 + May=115000 + Jun=120000 = 345000
    assert result["revenue_total"] == pytest.approx(345000.0)


# ── T18-02c: specific month "June 2026" ──────────────────────────────────────

@pytest.mark.asyncio
async def test_t18_02c_named_month_detected():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("revenue summary for June 2026")

    assert "June" in result["period"]
    assert "2026" in result["period"]
    assert result["revenue_total"] == pytest.approx(120000.0)


# ── T18-03: GPT-4o failure → narrative="narrative unavailable", success=True ─

@pytest.mark.asyncio
async def test_t18_03_gpt_failure_returns_narrative_unavailable():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("OpenAI API down"))

    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("revenue overview")

    assert result["success"] is True
    assert result["narrative"] == "narrative unavailable"
    # Data should still be present
    assert len(result["product_breakdown"]) == 3
    assert len(result["top_accounts"]) == 10
    assert isinstance(result["revenue_total"], float)


# ── T18-04: one tool fails → that section empty, others proceed ──────────────

@pytest.mark.asyncio
async def test_t18_04_one_tool_fails_others_continue():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock,
               return_value={"success": False, "error_code": "DB_ERROR"}), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("revenue overview")

    assert result["success"] is True
    assert result["revenue_total"] == 0.0       # no revenue data
    assert len(result["product_breakdown"]) == 3  # still populated
    assert len(result["top_accounts"]) == 10


# ── T18-05: result contains all required keys ─────────────────────────────────

@pytest.mark.asyncio
async def test_t18_05_result_shape():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("Q1 2026 executive summary")

    required = {"success", "question", "period", "revenue_total",
                "product_breakdown", "top_accounts", "outstanding", "narrative"}
    assert required.issubset(result.keys())
    assert result["question"] == "Q1 2026 executive summary"


# ── T18-06: GPT-4o markdown-fenced JSON handled ───────────────────────────────

@pytest.mark.asyncio
async def test_t18_06_gpt_markdown_fenced_json_handled():
    fenced = '```json\n{"narrative": "Fenced narrative."}\n```'
    msg = MagicMock()
    msg.content = fenced
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)

    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         patch(f"{_MODULE}.AsyncOpenAI", return_value=mock_client), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("revenue summary")

    assert result["narrative"] == "Fenced narrative."


# ── T18-07: default period when no period keyword in question ─────────────────

@pytest.mark.asyncio
async def test_t18_07_default_period_last_12_months():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("give me an executive summary")

    assert result["period"] == "last 12 months"
    # All 6 months summed: 92000+98000+105000+110000+115000+120000 = 640000
    assert result["revenue_total"] == pytest.approx(640000.0)


# ── T18-08: audit log shows TOOL_NAME='insight_agent' ────────────────────────

@pytest.mark.asyncio
async def test_t18_08_audit_tool_name_is_insight_agent():
    audit_mock = AsyncMock(return_value=True)

    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.insight_agent import run
        await run("revenue overview for Q1 2026")

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "insight_agent"


# ── T18-08b: "last 3 months" period detected ─────────────────────────────────

@pytest.mark.asyncio
async def test_t18_08b_last_n_months_period():
    with patch(f"{_MODULE}._billing.get_monthly_revenue",
               new_callable=AsyncMock, return_value=_monthly_revenue_data()), \
         patch(f"{_MODULE}._billing.get_revenue_by_product_type",
               new_callable=AsyncMock, return_value=_product_breakdown_data()), \
         patch(f"{_MODULE}._usage.get_top_usage_accounts",
               new_callable=AsyncMock, return_value=_top_accounts_data()), \
         patch(f"{_MODULE}._billing.get_unpaid_bills",
               new_callable=AsyncMock, return_value=_unpaid_bills_data()), \
         _patch_openai(_openai_narrative_response()), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.insight_agent import run
        result = await run("what was revenue in the last 3 months")

    assert result["period"] == "last 3 months"


# ── Integration tests (hit real Oracle DB + real OpenAI API) ──────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t18_01_integration_all_tools_called(db_conn):
    from src.agents.insight_agent import run
    result = await run("give me an executive revenue overview")
    assert result["success"] is True
    assert isinstance(result["product_breakdown"], list)
    assert isinstance(result["top_accounts"], list)
    assert isinstance(result["outstanding"], list)
    assert isinstance(result["revenue_total"], float)
    assert result["narrative"] != ""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t18_02_integration_q1_period(db_conn):
    from src.agents.insight_agent import run
    result = await run("give me the Q1 2026 revenue summary")
    assert result["success"] is True
    assert "Q1" in result["period"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t18_07_integration_gpt_failure_graceful(db_conn):
    """GPT-4o failure should still return data with narrative unavailable."""
    import os as _os
    original = _os.environ.get("OPENAI_API_KEY", "")
    _os.environ["OPENAI_API_KEY"] = "sk-invalid-key-for-test"
    try:
        from src.agents.insight_agent import run
        result = await run("executive summary")
        assert result["success"] is True
        assert result["narrative"] == "narrative unavailable"
        assert isinstance(result["product_breakdown"], list)
    finally:
        _os.environ["OPENAI_API_KEY"] = original


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t18_08_integration_audit_log(db_conn):
    from src.agents.insight_agent import run
    from src.tools.approval import get_audit_log
    await run("revenue summary")
    log = await get_audit_log(tool_name="insight_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "insight_agent" for r in log["data"])
