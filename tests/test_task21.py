"""
TASK 21 — onboarding_agent
Unit tests: T21-01 through T21-14

Unit tests mock the 5 step functions:
  step 1: _writes.create_customer
  steps 2-5: _step2_address, _step3_contact, _step4_account, _step5_product

Integration tests hit real Oracle DB.
"""
import pytest
from unittest.mock import AsyncMock, patch

_MODULE = "src.agents.onboarding_agent"

# ── Valid params fixture ──────────────────────────────────────────────────────

_VALID_PARAMS = {
    "customer_name":      "Global Telecom Ltd",
    "company_code":       "INV0001",
    "customer_type_code": "CORP",
    "address_type":       "BILLING",
    "address_line1":      "1 Network Drive",
    "city":               "Mumbai",
    "country":            "IN",
    "contact_name":       "Priya Sharma",
    "designation":        "CFO",
    "email":              "priya@globaltelecom.in",
    "phone_number":       "+91-9876543210",
    "account_name":       "Global Telecom Main Account",
    "currency_code":      "INR",
    "product_code":       "PROD0048",
    "start_date":         "2026-07-01",
    "requested_by":       "onboarding_user",
}


def _step_result(request_id: int, extra: dict | None = None) -> dict:
    r = {"success": True, "request_id": request_id, "status": "PENDING",
         "summary": f"Pending approval: request #{request_id}"}
    if extra:
        r.update(extra)
    return r


def _fail_result(message: str = "DB error") -> dict:
    return {"success": False, "error_code": "NOT_FOUND", "message": message}


def _patches_all(m1, m2, m3, m4, m5, audit=None):
    """Return a list of context-manager patches for all 5 step functions."""
    patchers = [
        patch(f"{_MODULE}._writes.create_customer", m1),
        patch(f"{_MODULE}._step2_address", m2),
        patch(f"{_MODULE}._step3_contact", m3),
        patch(f"{_MODULE}._step4_account", m4),
        patch(f"{_MODULE}._step5_product", m5),
    ]
    if audit is not None:
        patchers.append(patch(f"{_MODULE}.log_audit", audit))
    else:
        patchers.append(patch(f"{_MODULE}.log_audit", new_callable=AsyncMock))
    return patchers


# ── T21-01: all 5 steps succeed → 5 PENDING entries ──────────────────────────

@pytest.mark.asyncio
async def test_t21_01_all_five_steps_succeed():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(5))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is True
    assert result["steps_completed"] == 5
    assert result["total_steps"] == 5
    assert len(result["steps"]) == 5
    assert all(s["status"] == "PENDING" for s in result["steps"])
    assert [s["request_id"] for s in result["steps"]] == [1, 2, 3, 4, 5]


# ── T21-02: Pydantic validation fails → early exit, no DB calls ───────────────

@pytest.mark.asyncio
async def test_t21_02_pydantic_validation_fails_on_missing_required():
    mock_create = AsyncMock()

    with patch(f"{_MODULE}._writes.create_customer", mock_create), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run({"customer_name": "Only Name"})

    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"
    assert result["steps"] == []
    assert result["steps_completed"] == 0
    mock_create.assert_not_awaited()


# ── T21-03: Step 1 (create_customer) fails → only 1 item, FAILED ─────────────

@pytest.mark.asyncio
async def test_t21_03_step1_failure_stops_at_step1():
    m1 = AsyncMock(return_value=_fail_result("Company code XXXX not found"))
    m2 = AsyncMock()

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is False
    assert len(result["steps"]) == 1
    assert result["steps"][0]["step"] == 1
    assert result["steps"][0]["status"] == "FAILED"
    assert result["steps_completed"] == 0
    assert result["customer_number"] is None
    m2.assert_not_awaited()


# ── T21-04: Step 2 (_step2_address) fails → 1 PENDING + 1 FAILED ─────────────

@pytest.mark.asyncio
async def test_t21_04_step2_failure_stops_after_step1():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_fail_result("city is required"))
    m3 = AsyncMock()

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is False
    assert len(result["steps"]) == 2
    assert result["steps"][0]["status"] == "PENDING"
    assert result["steps"][1]["status"] == "FAILED"
    assert result["steps_completed"] == 1
    m3.assert_not_awaited()


# ── T21-05: customer_number from step 1 passed to steps 2, 3, 4 ──────────────

@pytest.mark.asyncio
async def test_t21_05_customer_number_propagated():
    cust_num = "CUST-999999"
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": cust_num}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(5))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["customer_number"] == cust_num
    # Each helper receives customer_number as first positional arg
    assert m2.call_args.args[0] == cust_num
    assert m3.call_args.args[0] == cust_num
    assert m4.call_args.args[0] == cust_num


# ── T21-06: account_number from step 4 passed to step 5 ──────────────────────

@pytest.mark.asyncio
async def test_t21_06_account_number_propagated():
    acc_num = "ACC-888888"
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": acc_num}))
    m5 = AsyncMock(return_value=_step_result(5))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["account_number"] == acc_num
    # _step5_product receives account_number as second positional arg
    assert m5.call_args.args[1] == acc_num


# ── T21-07: step 3 (_step3_contact) fails → 2 PENDING + 1 FAILED ─────────────

@pytest.mark.asyncio
async def test_t21_07_step3_failure():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_fail_result("email is required"))
    m4 = AsyncMock()

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is False
    assert result["steps_completed"] == 2
    assert result["steps"][2]["status"] == "FAILED"
    m4.assert_not_awaited()


# ── T21-08: step 4 (_step4_account) fails → 3 PENDING + 1 FAILED ─────────────

@pytest.mark.asyncio
async def test_t21_08_step4_failure():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_fail_result("currency INR not found"))
    m5 = AsyncMock()

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is False
    assert result["steps_completed"] == 3
    assert result["steps"][3]["status"] == "FAILED"
    assert result["account_number"] is None
    m5.assert_not_awaited()


# ── T21-09: step 5 (_step5_product) fails → 4 PENDING + 1 FAILED ─────────────

@pytest.mark.asyncio
async def test_t21_09_step5_failure():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_fail_result("product PROD0048 not found"))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    assert result["success"] is False
    assert result["steps_completed"] == 4
    assert result["steps"][4]["status"] == "FAILED"


# ── T21-10: result shape correct on full success ──────────────────────────────

@pytest.mark.asyncio
async def test_t21_10_result_shape_full_success():
    m1 = AsyncMock(return_value=_step_result(10, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(11))
    m3 = AsyncMock(return_value=_step_result(12))
    m4 = AsyncMock(return_value=_step_result(13, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(14))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    required = {"success", "steps", "customer_number", "account_number",
                "total_steps", "steps_completed"}
    assert required.issubset(result.keys())
    assert result["customer_number"] == "CUST-000001"
    assert result["account_number"] == "ACC-000001"


# ── T21-11: audit tool_name='onboarding_agent', action_type='WRITE' ───────────

@pytest.mark.asyncio
async def test_t21_11_audit_on_success():
    audit_mock = AsyncMock(return_value=True)
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(5))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.onboarding_agent import run
        await run(_VALID_PARAMS)

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args[0][0] == "onboarding_agent"
    assert audit_mock.call_args[0][3] == "WRITE"
    assert audit_mock.call_args[0][5] == "SUCCESS"


# ── T21-12: audit NOT called on validation error ──────────────────────────────

@pytest.mark.asyncio
async def test_t21_12_audit_not_called_on_validation_error():
    audit_mock = AsyncMock(return_value=True)

    with patch(f"{_MODULE}.log_audit", audit_mock):
        from src.agents.onboarding_agent import run
        await run({"customer_name": "Only"})

    audit_mock.assert_not_awaited()


# ── T21-13: step numbers and descriptions are correct ─────────────────────────

@pytest.mark.asyncio
async def test_t21_13_step_numbers_and_descriptions():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(5))

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(_VALID_PARAMS)

    for i, step in enumerate(result["steps"], start=1):
        assert step["step"] == i
    assert "customer" in result["steps"][0]["description"].lower()
    assert "address" in result["steps"][1]["description"].lower()
    assert "contact" in result["steps"][2]["description"].lower()
    assert "account" in result["steps"][3]["description"].lower()
    assert "product" in result["steps"][4]["description"].lower()


# ── T21-14: requested_by default is 'mcp_user' when not provided ─────────────

@pytest.mark.asyncio
async def test_t21_14_requested_by_defaults_to_mcp_user():
    m1 = AsyncMock(return_value=_step_result(1, {"customer_number": "CUST-000001"}))
    m2 = AsyncMock(return_value=_step_result(2))
    m3 = AsyncMock(return_value=_step_result(3))
    m4 = AsyncMock(return_value=_step_result(4, {"account_number": "ACC-000001"}))
    m5 = AsyncMock(return_value=_step_result(5))

    params_no_requestor = {k: v for k, v in _VALID_PARAMS.items()
                           if k != "requested_by"}

    with patch(f"{_MODULE}._writes.create_customer", m1), \
         patch(f"{_MODULE}._step2_address", m2), \
         patch(f"{_MODULE}._step3_contact", m3), \
         patch(f"{_MODULE}._step4_account", m4), \
         patch(f"{_MODULE}._step5_product", m5), \
         patch(f"{_MODULE}.log_audit", new_callable=AsyncMock):
        from src.agents.onboarding_agent import run
        result = await run(params_no_requestor)

    assert result["success"] is True
    assert m1.call_args.kwargs["requested_by"] == "mcp_user"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests (hit real Oracle DB)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t21_01_integration_all_steps_queued(db_conn):
    from src.agents.onboarding_agent import run
    result = await run(_VALID_PARAMS)
    # All 5 approval requests should be PENDING
    assert result["success"] is True
    assert result["steps_completed"] == 5
    assert result["total_steps"] == 5
    assert all(s["status"] == "PENDING" for s in result["steps"])
    assert result["customer_number"] is not None
    assert result["account_number"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t21_02_integration_validation_error(db_conn):
    from src.agents.onboarding_agent import run
    result = await run({"customer_name": "incomplete"})
    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t21_11_integration_audit_log(db_conn):
    from src.agents.onboarding_agent import run
    from src.tools.approval import get_audit_log
    await run(_VALID_PARAMS)
    log = await get_audit_log(tool_name="onboarding_agent", limit=5)
    assert log["success"] is True
    assert log["row_count"] >= 1
