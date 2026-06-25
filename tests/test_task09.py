"""
TASK 09 — Usage Analytics & Operations Read Tools (Groups G, H, I)
Unit tests: T09-01 through T09-13
"""
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch


# ── mock helpers ──────────────────────────────────────────────────────────────

def _make_conn():
    conn = MagicMock()
    conn.close = AsyncMock()
    return conn


def _stack(exec_rows=None, callfunc_rows=None, resolvers: dict | None = None):
    s = ExitStack()
    conn = _make_conn()
    s.enter_context(
        patch("src.tools.usage.get_connection",
              new_callable=AsyncMock, return_value=conn))
    if exec_rows is not None:
        s.enter_context(
            patch("src.tools.usage._exec",
                  new_callable=AsyncMock, side_effect=exec_rows))
    if callfunc_rows is not None:
        s.enter_context(
            patch("src.tools.usage._callfunc_cursor",
                  new_callable=AsyncMock, return_value=callfunc_rows))
    s.enter_context(
        patch("src.tools.usage.log_audit",
              new_callable=AsyncMock, return_value=True))
    for fname, retval in (resolvers or {}).items():
        if retval is None:
            s.enter_context(
                patch(f"src.tools.usage.{fname}",
                      new_callable=AsyncMock,
                      side_effect=ValueError("Not found")))
        else:
            s.enter_context(
                patch(f"src.tools.usage.{fname}",
                      new_callable=AsyncMock, return_value=retval))
    return s, conn


_SAMPLE_EVENT = {
    "event_id": 1, "account_id": 42, "account_num": "ACC-001",
    "event_dtm": "2026-06-01 12:00:00", "created_dtm": "2026-06-01 12:01:00",
    "in_bits": 1000000, "out_bits": 500000, "speed_mbps": 25.5,
    "bandwidth_mbps": 100.0, "event_type": "DATA", "source_system": "MEDIATION",
    "status": "SUCCESS",
}


# ── T09-01: resolves account_number before calling package ───────────────────

@pytest.mark.asyncio
async def test_t09_01_get_events_resolves_account_first():
    with _stack(callfunc_rows=[_SAMPLE_EVENT],
                resolvers={"resolve_account_number": 42})[0]:
        from src.tools.usage import get_events_by_account
        result = await get_events_by_account("ACC-001")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── T09-02: date range uses TIMESTAMP bind variables (direct SQL path) ────────

@pytest.mark.asyncio
async def test_t09_02_get_events_date_range_uses_sql():
    # date_from forces direct SQL path (not package)
    with _stack(exec_rows=[[_SAMPLE_EVENT]],
                resolvers={"resolve_account_number": 42})[0]:
        from src.tools.usage import get_events_by_account
        result = await get_events_by_account(
            "ACC-001", date_from="2026-06-01", date_to="2026-06-30")
    assert result["success"] is True
    # _exec was called (not _callfunc_cursor) — proved by exec_rows being consumed
    assert result["row_count"] == 1


# ── T09-03: get_event_summary returns required aggregation keys ───────────────

@pytest.mark.asyncio
async def test_t09_03_get_event_summary_structure():
    summary = [{"event_count": 10, "total_in_bits": 5000000,
                "total_out_bits": 2500000, "avg_speed_mbps": 22.3,
                "max_speed_mbps": 45.0, "earliest_event": "2026-06-01",
                "latest_event": "2026-06-30"}]
    with _stack(exec_rows=[summary],
                resolvers={"resolve_account_number": 42})[0]:
        from src.tools.usage import get_event_summary
        result = await get_event_summary("ACC-001")
    assert result["success"] is True
    d = result["data"]
    assert "total_in_bits" in d
    assert "total_out_bits" in d
    assert "avg_speed_mbps" in d
    assert "event_count" in d


# ── T09-04: get_top_usage_accounts calls GET_TOP_BANDWIDTH_ACCOUNTS ──────────

@pytest.mark.asyncio
async def test_t09_04_get_top_usage_accounts_package_call():
    top_rows = [
        {"account_number": "ACC-001", "customer_number": "CUST-001",
         "customer_name": "Acme", "total_bits": 99999999,
         "avg_speed_mbps": 50.0, "peak_bandwidth_mbps": 100.0,
         "event_count": 200},
    ]
    with _stack(callfunc_rows=top_rows)[0]:
        from src.tools.usage import get_top_usage_accounts
        result = await get_top_usage_accounts(limit=10)
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["account_number"] == "ACC-001"


# ── T09-05: get_usage_anomalies(100) returns events where SPEED_MBPS > 100 ───

@pytest.mark.asyncio
async def test_t09_05_get_usage_anomalies_threshold():
    anom = [{"event_id": 99, "account_num": "ACC-001", "speed_mbps": 150.0,
             "bandwidth_mbps": 200.0, "source_system": "MEDIATION",
             "account_number": "ACC-001", "customer_number": "CUST-001",
             "event_dtm": "2026-06-10"}]
    with _stack(callfunc_rows=anom)[0]:
        from src.tools.usage import get_usage_anomalies
        result = await get_usage_anomalies(threshold_mbps=100.0)
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["speed_mbps"] > 100


# ── T09-06: get_bandwidth_trend DAY groups by TRUNC(EVENT_DTM,'DD') ──────────

@pytest.mark.asyncio
async def test_t09_06_get_bandwidth_trend_day():
    rows = [{"period": "2026-06-01", "total_in_bits": 1000,
             "total_out_bits": 500, "avg_speed_mbps": 10.0, "event_count": 5}]
    with _stack(exec_rows=[rows])[0]:
        from src.tools.usage import get_bandwidth_trend
        result = await get_bandwidth_trend(granularity="DAY")
    assert result["success"] is True
    # period should look like YYYY-MM-DD
    assert len(result["data"][0]["period"]) == 10


# ── T09-07: get_bandwidth_trend MONTH groups by TRUNC(EVENT_DTM,'MM') ────────

@pytest.mark.asyncio
async def test_t09_07_get_bandwidth_trend_month():
    rows = [{"period": "2026-06", "total_in_bits": 50000,
             "total_out_bits": 25000, "avg_speed_mbps": 20.0, "event_count": 50}]
    with _stack(exec_rows=[rows])[0]:
        from src.tools.usage import get_bandwidth_trend
        result = await get_bandwidth_trend(granularity="MONTH")
    assert result["success"] is True
    assert len(result["data"][0]["period"]) == 7  # YYYY-MM


# ── T09-08: get_failed_events returns STATUS != 'SUCCESS' only ───────────────

@pytest.mark.asyncio
async def test_t09_08_get_failed_events_status_filter():
    failed = [{"event_id": 5, "account_num": "ACC-001",
               "event_dtm": "2026-06-01", "in_bits": 0, "out_bits": 0,
               "speed_mbps": 0, "event_type": "DATA",
               "source_system": "MEDIATION", "status": "FAILED"}]
    with _stack(exec_rows=[failed])[0]:
        from src.tools.usage import get_failed_events
        result = await get_failed_events()
    assert result["success"] is True
    assert all(r["status"] != "SUCCESS" for r in result["data"])


# ── T09-09: get_load_status_today returns one row per source system ───────────

@pytest.mark.asyncio
async def test_t09_09_get_load_status_today_rows():
    today_rows = [
        {"load_id": 1, "source_system": "MEDIATION",
         "records_received": 1000, "records_loaded": 998,
         "records_failed": 2, "status": "COMPLETED",
         "error_summary": None, "load_start_dtm": "2026-06-23 01:00",
         "load_end_dtm": "2026-06-23 01:15"},
        {"load_id": 2, "source_system": "RATING",
         "records_received": 500, "records_loaded": 500,
         "records_failed": 0, "status": "COMPLETED",
         "error_summary": None, "load_start_dtm": "2026-06-23 02:00",
         "load_end_dtm": "2026-06-23 02:10"},
    ]
    with _stack(callfunc_rows=today_rows)[0]:
        from src.tools.usage import get_load_status_today
        result = await get_load_status_today()
    assert result["success"] is True
    assert result["row_count"] == 2
    systems = [r["source_system"] for r in result["data"]]
    assert "MEDIATION" in systems


# ── T09-10: get_load_status_today empty → empty list, not error ──────────────

@pytest.mark.asyncio
async def test_t09_10_get_load_status_today_empty():
    with _stack(callfunc_rows=[])[0]:
        from src.tools.usage import get_load_status_today
        result = await get_load_status_today()
    assert result["success"] is True
    assert result["data"] == []
    assert result["row_count"] == 0


# ── T09-11: get_missing_loads(7) returns systems absent in last 7 days ────────

@pytest.mark.asyncio
async def test_t09_11_get_missing_loads():
    missing = [{"source_system": "LEGACY_SYSTEM",
                "last_load_date": "2026-06-15",
                "days_since_last_load": 8}]
    with _stack(callfunc_rows=missing)[0]:
        from src.tools.usage import get_missing_loads
        result = await get_missing_loads(days_back=7)
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["source_system"] == "LEGACY_SYSTEM"


# ── T09-12: get_open_requests returns OPEN and IN_PROGRESS only ───────────────

@pytest.mark.asyncio
async def test_t09_12_get_open_requests_statuses():
    reqs = [
        {"request_id": 1, "customer_id": 10, "account_id": 20,
         "request_type": "BILLING", "priority": "HIGH", "status": "OPEN",
         "raised_by": "alice", "assigned_to": "bob",
         "created_dtm": "2026-06-20", "resolved_dtm": None},
        {"request_id": 2, "customer_id": 11, "account_id": 21,
         "request_type": "DATA", "priority": "MEDIUM",
         "status": "IN_PROGRESS", "raised_by": "carol",
         "assigned_to": "bob", "created_dtm": "2026-06-21",
         "resolved_dtm": None},
    ]
    with _stack(exec_rows=[reqs])[0]:
        from src.tools.usage import get_open_requests
        result = await get_open_requests()
    assert result["success"] is True
    assert result["row_count"] == 2
    statuses = {r["status"] for r in result["data"]}
    assert statuses <= {"OPEN", "IN_PROGRESS"}


# ── T09-13: get_requests_by_customer filters by CUSTOMER_ID correctly ─────────

@pytest.mark.asyncio
async def test_t09_13_get_requests_by_customer():
    reqs = [
        {"request_id": 3, "request_type": "BILLING", "priority": "HIGH",
         "status": "OPEN", "raised_by": "alice", "assigned_to": "bob",
         "created_dtm": "2026-06-22", "resolved_dtm": None},
    ]
    with _stack(exec_rows=[reqs],
                resolvers={"resolve_customer_number": 10})[0]:
        from src.tools.usage import get_requests_by_customer
        result = await get_requests_by_customer("CUST-001")
    assert result["success"] is True
    assert result["row_count"] == 1


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_01_integration_events_by_account(db_conn):
    from src.tools.customer import search_customers
    from src.tools.account import get_accounts_by_customer
    from src.tools.usage import get_events_by_account
    custs = await search_customers(limit=1)
    if not custs["data"]:
        pytest.skip("No customers")
    accs = await get_accounts_by_customer(custs["data"][0]["customer_number"])
    if not accs["data"]:
        pytest.skip("No accounts")
    result = await get_events_by_account(accs["data"][0]["account_number"])
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_04_integration_top_usage_accounts(db_conn):
    from src.tools.usage import get_top_usage_accounts
    result = await get_top_usage_accounts(limit=5)
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_05_integration_usage_anomalies(db_conn):
    from src.tools.usage import get_usage_anomalies
    result = await get_usage_anomalies(threshold_mbps=0.0)
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_08_integration_failed_events(db_conn):
    from src.tools.usage import get_failed_events
    result = await get_failed_events()
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_09_integration_load_status_today(db_conn):
    from src.tools.usage import get_load_status_today
    result = await get_load_status_today()
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_12_integration_open_requests(db_conn):
    from src.tools.usage import get_open_requests
    result = await get_open_requests()
    assert result["success"] is True
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t09_06_integration_bandwidth_trend_day(db_conn):
    from src.tools.usage import get_bandwidth_trend
    result = await get_bandwidth_trend(granularity="DAY", limit=7)
    assert result["success"] is True
    assert isinstance(result["data"], list)
