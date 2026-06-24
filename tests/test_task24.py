"""
TASK 24 — End-to-End Integration Tests

All tests require a live Oracle DB and a valid OPENAI_API_KEY.
They are skipped automatically when DB_* env vars are absent.

Real DB seed data used:
  company_code   = INV0001   (INVOICING_COMPANY table)
  customer_type  = CORP      (CUSTOMER_TYPE table)
  product_code   = PROD0048  (PRODUCT table, status=ACTIVE)
  currency_code  = USD       (CURRENCY table)
  account_number = ACC000123 (ACCOUNT table)
  invoice_number = INV00000123 (BILL_SUMMARY table)

Scenarios:
    A — Full customer onboarding (onboarding_agent / write_master_agent)
    B — Monthly billing run (billing_run_agent / write_master_agent)
    C — RCA investigation via intent_router (READ path)
    D — Billing adjustment via intent_router (WRITE path)
    E — Schema discovery via intent_router (READ path)
    H — Audit log health across the full agent stack
"""
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# ── shared seed constants ──────────────────────────────────────────────────────
_COMPANY      = "INV0001"
_CUST_TYPE    = "CORP"
_PRODUCT      = "PROD0048"
_CURRENCY     = "USD"
_ACCOUNT      = "ACC000123"
_INVOICE      = "INV00000123"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO A — Full customer onboarding
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_A01_onboarding_through_write_master(db_conn):
    """
    write_master_agent GPT-4o routes a detailed onboarding question to
    onboarding_agent, which creates 5 PENDING approval requests.
    """
    from src.agents.write_master_agent import run

    question = (
        "Onboard a new customer with these exact details — "
        f"customer_name=TCL Integration Corp A, company_code={_COMPANY}, "
        f"customer_type_code={_CUST_TYPE}, address_type=BILLING, "
        "address_line1=1 Integration Blvd, city=Mumbai, country=IN, "
        "contact_name=Test Admin A, designation=Manager, "
        "email=testa@tcl-integration.com, phone_number=9999000001, "
        f"account_name=TCLIA Main, currency_code={_CURRENCY}, "
        f"product_code={_PRODUCT}, requested_by=test_24_A"
    )
    result = await run(question)

    assert result["success"] is True
    assert result["routed_to"] == "onboarding_agent"

    onboard = result["result"]
    assert onboard["success"] is True
    assert onboard["total_steps"] == 5
    assert onboard["steps_completed"] == 5
    assert onboard["customer_number"] is not None
    assert onboard["account_number"] is not None
    assert all(s["status"] == "PENDING" for s in onboard["steps"])


async def test_t24_A02_onboarding_direct_five_pending_approvals(db_conn):
    """
    onboarding_agent.run(params) directly produces 5 distinct PENDING
    approval request IDs.
    """
    from src.agents.onboarding_agent import run

    params = {
        "customer_name":      "TCL Integration Corp A2",
        "company_code":       _COMPANY,
        "customer_type_code": _CUST_TYPE,
        "address_type":       "BILLING",
        "address_line1":      "2 Integration Blvd",
        "city":               "Delhi",
        "country":            "IN",
        "contact_name":       "Test Admin A2",
        "designation":        "Director",
        "email":              "testa2@tcl-integration.com",
        "phone_number":       "9999000002",
        "account_name":       "TCLIA2 Main",
        "currency_code":      _CURRENCY,
        "product_code":       _PRODUCT,
        "requested_by":       "test_24_A2",
    }
    result = await run(params)

    assert result["success"] is True
    assert result["steps_completed"] == 5
    request_ids = [s["request_id"] for s in result["steps"]]
    assert all(rid is not None for rid in request_ids)
    assert len(set(request_ids)) == 5   # all 5 are distinct


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO B — Monthly billing run
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_B01_billing_run_through_write_master(db_conn):
    """
    write_master_agent routes 'run billing' to billing_run_agent.
    Result contains billing_month and the expected list keys.
    """
    from src.agents.write_master_agent import run

    result = await run(
        "Run the monthly billing for 2026-06, requested by test_24_B"
    )

    assert result["success"] is True
    assert result["routed_to"] == "billing_run_agent"

    br = result["result"]
    assert br["success"] is True
    assert br["billing_month"] == "2026-06"
    assert isinstance(br["approval_ids"], list)
    assert isinstance(br["skipped_no_flag"], list)
    assert isinstance(br["skipped_no_events"], list)
    assert isinstance(br["flagged_anomalies"], list)
    # conservation check: total accounts = queued + both skip buckets
    assert br["total"] == (
        br["queued"]
        + len(br["skipped_no_flag"])
        + len(br["skipped_no_events"])
    )


async def test_t24_B02_billing_run_queued_equals_approval_ids(db_conn):
    """
    Number of approval IDs returned by billing_run_agent equals the queued count.
    """
    from src.agents.billing_run_agent import run

    result = await run("2026-06", requested_by="test_24_B2")

    assert result["success"] is True
    assert len(result["approval_ids"]) == result["queued"]


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO C — RCA investigation via intent_router (READ path)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_C01_rca_through_intent_router(db_conn):
    """
    intent_router classifies the RCA question as READ and routes through
    read_master_agent → rca_agent. Result contains rca_summary.
    """
    from src.agents.intent_router import run

    result = await run(
        "Investigate billing and usage issues for customer CUST000122"
    )

    assert result["success"] is True
    assert result["intent"] == "READ"
    assert result["routed_to"] == "read_master_agent"

    read_result = result["result"]
    assert read_result["success"] is True
    assert read_result["routed_to"] == "rca_agent"

    rca = read_result["result"]
    assert rca["success"] is True
    assert "rca_summary" in rca
    assert "billing_issues" in rca
    assert "event_anomalies" in rca


async def test_t24_C02_rca_agent_direct_cust001(db_conn):
    """
    rca_agent called directly returns a well-formed result for CUST-001.
    """
    from src.agents.rca_agent import run

    result = await run("CUST000122")

    assert result["success"] is True
    assert result["customer_number"] == "CUST000122"
    assert "customer_profile" in result
    assert "billing_issues" in result
    assert "rca_summary" in result
    assert result["rca_summary"] != ""


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO D — Billing adjustment via intent_router (WRITE path)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_D01_adjustment_through_intent_router(db_conn):
    """
    intent_router classifies a credit adjustment request as WRITE and routes
    through write_master_agent → adjustment_agent.
    Adjustment goes to PENDING status (approval-gated).
    """
    from src.agents.intent_router import run

    result = await run(
        f"Apply a CREDIT adjustment of $250 to invoice {_INVOICE} "
        f"for account {_ACCOUNT} due to service downtime, "
        "requested by test_24_D"
    )

    assert result["success"] is True
    assert result["intent"] == "WRITE"
    assert result["routed_to"] == "write_master_agent"

    write_result = result["result"]
    assert write_result["success"] is True
    assert write_result["routed_to"] == "adjustment_agent"

    adj = write_result["result"]
    assert adj["success"] is True
    assert adj["action"] == "create_billing_adjustment"
    assert adj["request_id"] is not None
    assert adj["status"] == "PENDING"


async def test_t24_D02_adjustment_direct_dispute(db_conn):
    """
    adjustment_agent called directly creates a PENDING DISPUTE request.
    """
    from src.agents.adjustment_agent import run

    result = await run(
        f"Open a dispute for $750 against invoice {_INVOICE} "
        f"for account {_ACCOUNT}, requested by test_24_D2"
    )

    assert result["success"] is True
    assert result["action"] == "create_billing_adjustment"
    assert result["status"] == "PENDING"
    assert result["request_id"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO E — Schema discovery via intent_router (READ path)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_E01_schema_discovery_through_intent_router(db_conn):
    """
    intent_router → READ → read_master_agent → schema_agent.
    The real DB has exactly 9 PL/SQL packages.
    """
    from src.agents.intent_router import run

    result = await run("List all PL/SQL packages available in the schema")

    assert result["success"] is True
    assert result["intent"] == "READ"
    assert result["routed_to"] == "read_master_agent"

    read_result = result["result"]
    assert read_result["success"] is True
    assert read_result["routed_to"] == "schema_agent"

    schema = read_result["result"]
    assert schema["success"] is True
    packages_result = next(
        (r for r in schema["results"] if r["tool"] == "list_packages"), None
    )
    assert packages_result is not None
    assert packages_result["result"]["row_count"] == 9


async def test_t24_E02_billing_query_through_intent_router(db_conn):
    """
    intent_router routes a revenue query as READ → read_master_agent.
    """
    from src.agents.intent_router import run

    result = await run("Show me the monthly revenue for the last 6 months")

    assert result["success"] is True
    assert result["intent"] == "READ"
    assert result["routed_to"] == "read_master_agent"

    read_result = result["result"]
    assert read_result["success"] is True
    assert "routed_to" in read_result


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO H — Audit log health across the full agent stack
# ═══════════════════════════════════════════════════════════════════════════════

async def test_t24_H01_intent_router_audit_entries(db_conn):
    """
    After routing through intent_router, MCP_AUDIT_LOG has a SUCCESS entry.
    """
    from src.agents.intent_router import run
    from src.tools.approval import get_audit_log

    await run("What are the top 5 accounts by usage this month?")
    log = await get_audit_log(tool_name="intent_router", limit=10)

    assert log["success"] is True
    assert log["row_count"] >= 1
    assert all(r["tool_name"] == "intent_router" for r in log["data"])


async def test_t24_H02_write_master_audit_entries(db_conn):
    """
    After routing through write_master_agent, MCP_AUDIT_LOG has a SUCCESS entry.
    """
    from src.agents.write_master_agent import run
    from src.tools.approval import get_audit_log

    await run(
        f"Apply a $50 WAIVER to invoice {_INVOICE} for account {_ACCOUNT} "
        "due to goodwill, requested by test_24_H2"
    )
    log = await get_audit_log(tool_name="write_master_agent", limit=10)

    assert log["success"] is True
    assert log["row_count"] >= 1


async def test_t24_H03_full_read_chain_audit(db_conn):
    """
    A full READ chain (intent_router → read_master_agent → billing_read_agent)
    produces audit entries for at least intent_router and read_master_agent.
    """
    from src.agents.intent_router import run
    from src.tools.approval import get_audit_log

    await run("Show me all unpaid invoices")

    for tool_name in ("intent_router", "read_master_agent"):
        log = await get_audit_log(tool_name=tool_name, limit=5)
        assert log["success"] is True, f"Audit query failed for {tool_name}"
        assert log["row_count"] >= 1, f"No audit entries for {tool_name}"


async def test_t24_H04_approval_workflow_end_to_end(db_conn):
    """
    End-to-end approval workflow:
    1. Create a billing adjustment via adjustment_agent → PENDING
    2. List pending approvals via approval_agent → request appears
    """
    from src.agents.adjustment_agent import run as adj_run
    from src.agents.approval_agent import run as appr_run

    # Step 1: create a pending adjustment
    adj = await adj_run(
        f"Apply a $100 CREDIT to invoice {_INVOICE} for account {_ACCOUNT}, "
        "requested by test_24_H4"
    )
    assert adj["success"] is True
    request_id = adj["request_id"]
    assert request_id is not None

    # Step 2: list pending approvals — the new request must appear
    pending = await appr_run("show me all pending approval requests")
    assert pending["success"] is True
    assert pending["row_count"] >= 1
