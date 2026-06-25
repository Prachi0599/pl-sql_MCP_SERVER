"""
TASK 25 — New features added in this change set:
  * gpt-4o-mini as the default OpenAI model (env-driven)
  * DELETE write tools (note / address / contact / costed event)
  * rows_affected + change_summary on approval
  * DBA / database-administration tools (reads + maintenance writes)
  * chat.py conversation context (RCA recommendation follow-ups)

Unit tests (no DB / no OpenAI):  T25-01 .. T25-20
Integration tests (live Oracle): T25-30 .. T25-36   (auto-skip without DB)
"""
import json
import os
import importlib
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_WRITES = "src.tools.writes"
_DBA = "src.tools.dba"
_APPROVAL = "src.tools.approval"

_PENDING = {"request_id": 99, "status": "PENDING", "summary": "Pending approval: test"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn():
    c = MagicMock()
    c.close = AsyncMock()
    c.commit = AsyncMock()
    return c


def _patch(module, conn, exec_side=None, create_ret=None):
    s = ExitStack()
    s.enter_context(patch(f"{module}.get_connection",
                          new_callable=AsyncMock, return_value=conn))
    s.enter_context(patch(f"{module}.log_audit",
                          new_callable=AsyncMock, return_value=True))
    if exec_side is not None:
        s.enter_context(patch(f"{module}._exec",
                              new_callable=AsyncMock, side_effect=exec_side))
    if create_ret is not None:
        s.enter_context(patch(f"{module}.create_approval_request",
                              new_callable=AsyncMock, return_value=create_ret))
    return s


# ════════════════════════════════════════════════════════════════════════════
# 1) Model default — gpt-4o-mini, overridable via OPENAI_MODEL
# ════════════════════════════════════════════════════════════════════════════

def test_t25_01_default_model_is_gpt4o_mini():
    """Every agent must fall back to gpt-4o-mini when OPENAI_MODEL is unset."""
    import glob
    for f in glob.glob("src/agents/*.py"):
        txt = open(f, encoding="utf-8").read()
        if "_MODEL" in txt:
            assert 'os.environ.get("OPENAI_MODEL", "gpt-4o-mini")' in txt, \
                f"{f} does not default to gpt-4o-mini"


def test_t25_02_model_overridable_via_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "my-custom-model")
    import src.agents.intent_router as mod
    importlib.reload(mod)
    assert mod._MODEL == "my-custom-model"
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    importlib.reload(mod)


def test_t25_03_no_hardcoded_gpt4o_literal_in_agents():
    import glob
    offenders = []
    for f in glob.glob("src/agents/*.py") + ["chat.py"]:
        txt = open(f, encoding="utf-8").read()
        # the only allowed literal is gpt-4o-mini (and env-driven reads)
        if '"gpt-4o"' in txt:
            offenders.append(f)
    assert offenders == [], f"hardcoded gpt-4o literal remains in: {offenders}"


# ════════════════════════════════════════════════════════════════════════════
# 2) DELETE write tools
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_t25_04_delete_note_stages_delete_request():
    conn = _conn()
    with _patch(_WRITES, conn, exec_side=[[{"note_id": 5}]], create_ret=_PENDING):
        from src.tools.writes import delete_customer_note
        r = await delete_customer_note(5)
    assert r["success"] is True and r["status"] == "PENDING"


@pytest.mark.asyncio
async def test_t25_05_delete_note_missing_is_no_change():
    conn = _conn()
    with _patch(_WRITES, conn, exec_side=[[]], create_ret=_PENDING):
        from src.tools.writes import delete_customer_note
        r = await delete_customer_note(123456)
    assert r["no_change"] is True
    assert "nothing to delete" in r["message"]


@pytest.mark.asyncio
async def test_t25_06_delete_note_bad_id_validation_error():
    conn = _conn()
    with _patch(_WRITES, conn, exec_side=[[{"note_id": 1}]], create_ret=_PENDING):
        from src.tools.writes import delete_customer_note
        r = await delete_customer_note("not-a-number")
    assert r["success"] is False and r["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_t25_07_delete_contact_uses_multi_statement_payload():
    """Contact delete must remove CONTACT_DETAILS child then CONTACT parent."""
    conn = _conn()
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_WRITES, conn, exec_side=[[{"contact_id": 7}]]):
        with patch(f"{_WRITES}.create_approval_request",
                   new_callable=AsyncMock, side_effect=_cap):
            from src.tools.writes import delete_customer_contact
            r = await delete_customer_contact(7)
    assert r["success"] is True
    payload = json.loads(captured["new_value"])
    assert len(payload["statements"]) == 2
    assert "CONTACT_DETAILS" in payload["statements"][0]["sql"]
    assert captured["action_type"] == "DELETE"


@pytest.mark.asyncio
async def test_t25_08_delete_costed_event_action_type_delete():
    conn = _conn()
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_WRITES, conn, exec_side=[[{"event_id": 3}]]):
        with patch(f"{_WRITES}.create_approval_request",
                   new_callable=AsyncMock, side_effect=_cap):
            from src.tools.writes import delete_costed_event
            await delete_costed_event(3)
    assert captured["action_type"] == "DELETE"
    assert "DELETE FROM" in json.loads(captured["new_value"])["sql"]


# ════════════════════════════════════════════════════════════════════════════
# 3) approval — rows_affected + _describe_change
# ════════════════════════════════════════════════════════════════════════════

def test_t25_09_describe_update_before_after():
    from src.tools.approval import _describe_change
    # The "after" value comes from a new_* key in OLD_VALUE — NOT guessed from the
    # SQL bind params (which are numeric IDs, e.g. currency_id/account_id).
    old = json.dumps({"account_number": "ACC1",
                      "old_status": "ACTIVE", "new_status": "INACTIVE"})
    new = json.dumps({"params": [10, "INACTIVE"]})
    s = _describe_change("UPDATE", old, new, "UPDATE_ACCOUNT_STATUS", 1)
    assert "ACTIVE" in s and "INACTIVE" in s and "1 row" in s


def test_t25_09b_describe_currency_uses_code_not_id():
    """Regression: currency update must show 'INR' -> 'USD', never the account id."""
    from src.tools.approval import _describe_change
    old = json.dumps({"account_number": "ACC000122",
                      "old_currency": "INR", "new_currency": "USD"})
    new = json.dumps({"params": [3, 122]})   # [currency_id, account_id]
    s = _describe_change("UPDATE", old, new, "UPDATE_ACCOUNT_CURRENCY", 1)
    assert "'INR' -> 'USD'" in s and "122" not in s


def test_t25_10_describe_insert_and_delete():
    from src.tools.approval import _describe_change
    assert "created 1 row" in _describe_change("INSERT", None,
                                               json.dumps({"sql": "x"}), "INSERT_NOTE", 1)
    assert "deleted 2 rows" in _describe_change("DELETE", json.dumps({"note_id": 1}),
                                               json.dumps({"sql": "x"}), "DELETE_NOTE", 2)


@pytest.mark.asyncio
async def test_t25_11_dispatch_dml_reports_rows_affected():
    from src.tools import approval
    conn = _conn()
    cur = MagicMock()
    cur.rowcount = 1
    cur.execute = AsyncMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cur)
    cm.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cm)
    payload = json.dumps({"sql": "DELETE FROM X WHERE ID=:1", "params": [1]})
    res = await approval._dispatch_dml(conn, "DIRECT_SQL", "DELETE_X", payload)
    assert res["rows_affected"] == 1 and res["dispatched"] is True


# ════════════════════════════════════════════════════════════════════════════
# 4) DBA tools — privilege degradation + maintenance writes
# ════════════════════════════════════════════════════════════════════════════

def test_t25_12_is_missing_view_detects_ora942():
    from src.tools.dba import _is_missing_view
    assert _is_missing_view(Exception("ORA-00942: table or view does not exist"))
    assert not _is_missing_view(Exception("ORA-00001: unique constraint"))


@pytest.mark.asyncio
async def test_t25_13_active_sessions_degrades_on_missing_v_view():
    conn = _conn()
    with _patch(_DBA, conn, exec_side=Exception("ORA-00942: V_$SESSION")):
        from src.tools.dba import get_active_sessions
        r = await get_active_sessions()
    assert r["success"] is True and r["available"] is False
    assert "SELECT_CATALOG_ROLE" in r["message"]


@pytest.mark.asyncio
async def test_t25_14_get_unused_indexes_excludes_constraints():
    conn = _conn()
    rows = [{"index_name": "IX_FOO", "table_name": "T", "uniqueness": "NONUNIQUE",
             "index_type": "NORMAL", "num_rows": 10, "distinct_keys": 5,
             "last_analyzed": "2026-01-01", "columns": "A, B"}]
    with _patch(_DBA, conn, exec_side=[rows]):
        from src.tools.dba import get_unused_indexes
        r = await get_unused_indexes()
    assert r["success"] is True and r["row_count"] == 1
    assert "drop_index" in r["note"]


@pytest.mark.asyncio
async def test_t25_15_drop_index_refuses_constraint_index():
    conn = _conn()
    meta = [{"index_name": "PK_T", "table_name": "T", "uniqueness": "UNIQUE",
             "backs_constraint": 1}]
    with _patch(_DBA, conn, exec_side=[meta]):
        from src.tools.dba import drop_index
        r = await drop_index("PK_T")
    assert r["success"] is False and r["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_t25_16_drop_index_stages_for_nonconstraint():
    conn = _conn()
    meta = [{"index_name": "IX_FOO", "table_name": "T", "uniqueness": "NONUNIQUE",
             "backs_constraint": 0}]
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_DBA, conn, exec_side=[meta]):
        with patch(f"{_DBA}.create_approval_request",
                   new_callable=AsyncMock, side_effect=_cap):
            from src.tools.dba import drop_index
            r = await drop_index("ix_foo")
    assert r["success"] is True and r["status"] == "PENDING"
    assert captured["action_type"] == "DELETE"
    assert "DROP INDEX" in json.loads(captured["new_value"])["sql"]


@pytest.mark.asyncio
async def test_t25_17_gather_table_stats_missing_table_no_change():
    conn = _conn()
    with _patch(_DBA, conn, exec_side=[[]]):
        from src.tools.dba import gather_table_stats
        r = await gather_table_stats("NOPE")
    assert r.get("no_change") is True


# ════════════════════════════════════════════════════════════════════════════
# 5) chat.py conversation context
# ════════════════════════════════════════════════════════════════════════════

def _load_chat():
    import chat
    importlib.reload(chat)
    return chat


def test_t25_18_capture_rca_context_and_pick_index():
    chat = _load_chat()
    leaf = {"customer_number": "CUST000122",
            "recommended_actions": ["Chase invoice", "Reseat product", "Open ticket"],
            "rca_summary": "unpaid bills"}
    chat._capture_rca_context(leaf)
    assert chat.LAST_CONTEXT["customer_number"] == "CUST000122"
    assert chat._pick_action_index("apply recommendation 2", 3) == 2
    assert chat._pick_action_index("apply the second one", 3) == 2
    assert chat._pick_action_index("apply all of them", 3) == 0
    assert chat._pick_action_index("do the recommendation", 3) is None


def test_t25_19_reco_followup_builds_write_request():
    chat = _load_chat()
    chat.LAST_CONTEXT = {"customer_number": "CUST000122",
                         "recommended_actions": ["Chase the unpaid invoice", "Open a ticket"],
                         "rca_summary": "unpaid bills detected"}
    req = chat._reco_followup_request("please apply recommendation 1")
    assert req is not None
    assert "CUST000122" in req and "Chase the unpaid invoice" in req
    # 'apply all' joins every action
    req_all = chat._reco_followup_request("go ahead with all the recommendations")
    assert "Chase the unpaid invoice" in req_all and "Open a ticket" in req_all


def test_t25_20_followup_pronoun_appends_customer():
    chat = _load_chat()
    chat.LAST_CONTEXT = {"customer_number": "CUST000122",
                         "recommended_actions": [], "rca_summary": ""}
    out = chat._maybe_followup("what about his unpaid bills?")
    assert out is not None and "CUST000122" in out
    # unrelated message with no context reference → no rewrite
    chat.LAST_CONTEXT = None
    assert chat._maybe_followup("how many active customers?") is None


# ════════════════════════════════════════════════════════════════════════════
# 7) Bug fixes — maintenance change phrasing, no duplicate row count,
#    account-or-customer resolution, clearer missing-identifier errors
# ════════════════════════════════════════════════════════════════════════════

def test_t25_21_maintenance_change_summary_has_no_row_count():
    from src.tools.approval import _describe_change
    assert _describe_change("UPDATE", json.dumps({"table_name": "CUSTOMER"}),
                            json.dumps({"sql": "BEGIN .. END;"}),
                            "GATHER_TABLE_STATS", 0) == \
        "gathered optimizer statistics for CUSTOMER"
    assert _describe_change("DELETE", json.dumps({"index_name": "IX_FOO"}),
                            json.dumps({"sql": "DROP"}), "DROP_INDEX", 0) == \
        "dropped index IX_FOO"
    assert _describe_change("UPDATE", json.dumps({"object_name": "ACCOUNT_PKG"}),
                            json.dumps({"sql": "ALTER"}), "RECOMPILE_OBJECT", 0) == \
        "recompiled ACCOUNT_PKG"


def test_t25_22_update_summary_states_row_count_exactly_once():
    from src.tools.approval import _describe_change
    s = _describe_change("UPDATE", json.dumps({"old_status": "ACTIVE"}),
                         json.dumps({"params": [1, "INACTIVE"]}),
                         "UPDATE_ACCOUNT_STATUS", 1)
    assert s.count("1 row changed") == 1            # exactly once, not duplicated


@pytest.mark.asyncio
async def test_t25_23_resolve_account_or_customer_falls_back_to_customer():
    """A customer number with exactly one account resolves to that account."""
    from src.db import resolvers
    cur = MagicMock()
    # 1st execute = account lookup (miss), 2nd = customer's accounts (one hit)
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)
    cur.fetchall = AsyncMock(return_value=[(42, "ACC000150")])
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cur)
    cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cm)
    aid = await resolvers.resolve_account_or_customer(conn, "CUST000150")
    assert aid == 42


@pytest.mark.asyncio
async def test_t25_24_resolve_account_or_customer_multi_account_raises():
    from src.db import resolvers
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)
    cur.fetchall = AsyncMock(return_value=[(1, "ACC1"), (2, "ACC2")])
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cur)
    cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cm)
    with pytest.raises(ValueError, match="multiple accounts"):
        await resolvers.resolve_account_or_customer(conn, "CUST1")


@pytest.mark.asyncio
async def test_t25_25_terminate_product_missing_customer_clear_error():
    from src.tools.writes import terminate_customer_product
    r = await terminate_customer_product("", "PROD0048")
    assert r["success"] is False and r["error_code"] == "VALIDATION_ERROR"
    assert "customer_number is required" in r["message"]


# ════════════════════════════════════════════════════════════════════════════
# 8) Hard deletes, service-request fields, session-change recap, onboarding batch
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_t25_26_delete_account_stages_cascade_delete():
    conn = _conn()
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_WRITES, conn):
        with patch(f"{_WRITES}.resolve_account_number",
                   new_callable=AsyncMock, return_value=20):
            with patch(f"{_WRITES}.create_approval_request",
                       new_callable=AsyncMock, side_effect=_cap):
                from src.tools.writes import delete_account
                r = await delete_account("ACC000123")
    assert r["success"] is True
    assert captured["action_type"] == "DELETE"
    payload = json.loads(captured["new_value"])
    # cascade = several child deletes ending with the ACCOUNT row
    assert payload["statements"][-1]["sql"].strip().endswith("WHERE ACCOUNT_ID = :1")
    assert any("BILL_SUMMARY" in s["sql"] for s in payload["statements"])


@pytest.mark.asyncio
async def test_t25_27_delete_customer_stages_full_cascade():
    conn = _conn()
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_WRITES, conn):
        with patch(f"{_WRITES}.resolve_customer_number",
                   new_callable=AsyncMock, return_value=10):
            with patch(f"{_WRITES}.create_approval_request",
                       new_callable=AsyncMock, side_effect=_cap):
                from src.tools.writes import delete_customer
                r = await delete_customer("CUST000122")
    assert r["success"] is True
    tables = " ".join(s["sql"] for s in json.loads(captured["new_value"])["statements"])
    for t in ("ACCOUNT", "CONTACT", "ADDRESS", "CUSTOMER_NOTE", "SERVICE_REQUEST"):
        assert t in tables
    assert json.loads(captured["new_value"])["statements"][-1]["sql"].endswith(
        "WHERE CUSTOMER_ID = :1")


@pytest.mark.asyncio
async def test_t25_28_delete_account_requires_identifier():
    from src.tools.writes import delete_account, delete_customer
    assert (await delete_account(""))["error_code"] == "VALIDATION_ERROR"
    assert (await delete_customer(""))["error_code"] == "VALIDATION_ERROR"


def test_t25_29_session_change_recap_and_onboarding_steps():
    chat = _load_chat()
    # recap regex matches the user's phrasings, and ONLY answers from session log
    assert chat._CHANGE_RECAP.search("show me what you have changed")
    assert chat._CHANGE_RECAP.search("what did you create")
    assert not chat._CHANGE_RECAP.search("how many active customers")
    chat.SESSION_CHANGES.clear()
    assert "haven't applied any changes" in chat._format_session_changes()
    chat._record_change(101, "account status: 'ACTIVE' -> 'INACTIVE'", "update_account_status")
    recap = chat._format_session_changes()
    assert "request #101" in recap and "INACTIVE" in recap
    # onboarding bundle detection
    leaf = {"total_steps": 5, "customer_number": "CUST-1",
            "steps": [{"request_id": 1, "status": "PENDING", "description": "Create customer"},
                      {"request_id": 2, "status": "PENDING", "description": "Add address"}]}
    steps = chat._onboarding_steps(leaf)
    assert steps and len(steps) == 2 and steps[0]["request_id"] == 1
    assert chat._onboarding_steps({"data": []}) is None


def test_t25_30b_change_recap_regex_breadth():
    """Recap must catch 'inserted'/'show me the changes' but not read commands."""
    chat = _load_chat()
    for hit in ["show me what you have inserted", "show me the changes",
                "what did you create", "list recent updates",
                "show me what you changed", "what changes has made",
                "what changes were made", "which updates happened",
                "sjow me what you hage inserted"]:
        assert chat._CHANGE_RECAP.search(hit), hit
    for miss in ["show service requests", "how many active customers",
                 "Add a billing address for CUST000122",
                 "change account ACC000122 currency to USD",
                 "what is the account balance"]:
        assert not chat._CHANGE_RECAP.search(miss), miss


@pytest.mark.asyncio
async def test_t25_30c_currency_update_stores_new_code():
    """update_account_currency must persist the human new value (new_currency)."""
    conn = _conn()
    captured = {}

    async def _cap(c, **kw):
        captured.update(kw)
        return _PENDING

    with _patch(_WRITES, conn, exec_side=[[{"currency_code": "INR"}]]):
        with patch(f"{_WRITES}.resolve_account_or_customer",
                   new_callable=AsyncMock, return_value=42):
            with patch(f"{_WRITES}.resolve_currency_code",
                       new_callable=AsyncMock, return_value=7):
                with patch(f"{_WRITES}.create_approval_request",
                           new_callable=AsyncMock, side_effect=_cap):
                    from src.tools.writes import update_account_currency
                    await update_account_currency("ACC000122", "USD")
    old = json.loads(captured["old_value"])
    assert old["old_currency"] == "INR" and old["new_currency"] == "USD"


def test_t25_30d_past_change_phrase():
    from src.tools.approval import _past_change_phrase
    assert _past_change_phrase(
        "UPDATE", json.dumps({"old_currency": "INR", "new_currency": "USD"}),
        "UPDATE_ACCOUNT_CURRENCY") == "update account currency: 'INR' -> 'USD'"
    assert _past_change_phrase(
        "UPDATE", json.dumps({"table_name": "CUSTOMER"}),
        "GATHER_TABLE_STATS") == "gathered optimizer statistics for CUSTOMER"
    assert _past_change_phrase("INSERT", None, "CREATE_CUSTOMER") == "create customer"


@pytest.mark.asyncio
async def test_t25_30e_get_recent_changes_summarizes():
    conn = _conn()
    rows = [
        {"request_id": 50, "package_name": "ACCOUNT_PKG",
         "procedure_name": "UPDATE_ACCOUNT_STATUS", "action_type": "UPDATE",
         "old_value": json.dumps({"old_status": "ACTIVE", "new_status": "INACTIVE"}),
         "approved_by": "alice", "approved_dtm": "2026-06-26 10:00"},
    ]
    with _patch(_APPROVAL, conn, exec_side=[rows]):
        from src.tools.approval import get_recent_changes
        res = await get_recent_changes(5)
    assert res["success"] is True and res["row_count"] == 1
    assert res["data"][0]["summary"] == "update account status: 'ACTIVE' -> 'INACTIVE'"
    assert res["data"][0]["approved_by"] == "alice"


@pytest.mark.asyncio
async def test_t25_30f_recap_falls_back_to_history():
    """With no session changes, the recap pulls from the approval history."""
    chat = _load_chat()
    chat.SESSION_CHANGES.clear()
    fake = {"success": True, "data": [
        {"request_id": 77, "summary": "delete customer", "action_type": "DELETE",
         "approved_by": "bob", "approved_dtm": "2026-06-26 09:00"}]}
    with patch("src.tools.approval.get_recent_changes",
               new_callable=AsyncMock, return_value=fake):
        recap = await chat._change_recap()
    assert "approval history" in recap and "delete customer" in recap
    assert "request #77" in recap and "bob" in recap


# ════════════════════════════════════════════════════════════════════════════
# 6) Integration (live Oracle) — auto-skipped when DB unavailable
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_30_database_health_live():
    from src.tools.dba import get_database_health
    from src.db.pool import close_pool
    try:
        r = await get_database_health()
        assert r["success"] is True
        assert r["data"]["schema"] == "MCP_APP"
        assert "object_counts" in r["data"]
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_31_unused_indexes_live():
    from src.tools.dba import get_unused_indexes
    from src.db.pool import close_pool
    try:
        r = await get_unused_indexes()
        assert r["success"] is True
        assert isinstance(r["data"], list)
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_32_v_dollar_tools_dont_crash_live():
    """V$ tools must return success (live data or graceful degrade), never raise."""
    from src.tools import dba
    from src.db.pool import close_pool
    try:
        for fn in (dba.get_active_sessions, dba.get_blocking_sessions,
                   dba.get_slow_queries, dba.get_wait_events):
            r = await fn()
            assert r["success"] is True
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_37_get_recent_changes_live():
    from src.tools.approval import get_recent_changes
    from src.db.pool import close_pool
    try:
        r = await get_recent_changes(5)
        assert r["success"] is True
        assert isinstance(r["data"], list)
        for ch in r["data"]:
            assert ch.get("summary") and "request_id" in ch
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_35_service_requests_expose_full_fields_live():
    from src.tools.usage import get_open_requests
    from src.db.pool import close_pool
    try:
        r = await get_open_requests()
        assert r["success"] is True
        if r["data"]:
            row = r["data"][0]
            for field in ("description", "assigned_to",
                          "raised_by", "resolution_notes"):
                assert field in row, f"missing {field}"
            # raised_by is the single creator field — no duplicate created_by
            assert "created_by" not in row
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_36_hard_delete_customer_cascade_live():
    """Create a throwaway customer + account, approve, hard-delete, verify gone."""
    from src.tools import writes, approval
    from src.tools.approval import _exec
    from src.db.pool import get_connection, close_pool
    try:
        cr = await writes.create_customer("ZZ Pytest Del Co", "INV0001", "CORP")
        await approval.approve_request(cr["request_id"], "pytest")
        cust = cr["customer_number"]
        ac = await writes.create_account(cust, "ZZ Pytest Acct", "USD")
        await approval.approve_request(ac["request_id"], "pytest")
        acct = ac["account_number"]

        dr = await writes.delete_customer(cust)
        assert dr["status"] == "PENDING"
        dap = await approval.approve_request(dr["request_id"], "pytest")
        assert dap["success"] is True
        assert "deleted" in dap["change_summary"]

        conn = await get_connection()
        try:
            left_c = await _exec(
                conn, "SELECT COUNT(*) n FROM MCP_APP.CUSTOMER WHERE CUSTOMER_NUMBER=:1",
                [cust])
            left_a = await _exec(
                conn, "SELECT COUNT(*) n FROM MCP_APP.ACCOUNT WHERE ACCOUNT_NUMBER=:1",
                [acct])
        finally:
            await conn.close()
        assert left_c[0]["n"] == 0 and left_a[0]["n"] == 0
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_34_resolve_customer_to_account_live():
    """'change account status for customer CUST000150' must resolve to that
    customer's account instead of failing 'Account not found'."""
    from src.db.resolvers import resolve_account_or_customer
    from src.db.pool import get_connection, close_pool
    try:
        conn = await get_connection()
        try:
            aid = await resolve_account_or_customer(conn, "CUST000150")
            assert isinstance(aid, int) and aid > 0
        finally:
            await conn.close()
    finally:
        await close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_t25_33_delete_round_trip_live():
    """Create a note, approve (INSERT), then delete it, approve (DELETE).
    Verifies rows_affected and change_summary end-to-end. Net-zero on the DB."""
    from src.tools import writes, approval
    from src.db.pool import get_connection, close_pool
    try:
        conn = await get_connection()
        rows = await approval._exec(
            conn, "SELECT CUSTOMER_NUMBER FROM MCP_APP.CUSTOMER FETCH FIRST 1 ROW ONLY")
        await conn.close()
        cust = rows[0]["customer_number"]

        cr = await writes.add_customer_note(cust, "GENERAL",
                                            "T25 auto-delete note", "pytest")
        ins = await approval.approve_request(cr["request_id"], "pytest")
        assert ins["rows_affected"] == 1
        assert "created" in ins["change_summary"]

        conn = await get_connection()
        # NOTE_TEXT is a CLOB — use LIKE (CLOBs cannot be an '=' comparison key).
        nrows = await approval._exec(
            conn, "SELECT NOTE_ID FROM MCP_APP.CUSTOMER_NOTE "
                  "WHERE NOTE_TEXT LIKE 'T25 auto-delete note' "
                  "ORDER BY NOTE_ID DESC FETCH FIRST 1 ROW ONLY")
        await conn.close()
        nid = nrows[0]["note_id"]

        dr = await writes.delete_customer_note(nid)
        dap = await approval.approve_request(dr["request_id"], "pytest")
        assert dap["rows_affected"] == 1
        assert "deleted" in dap["change_summary"]

        # idempotent: deleting again is a no-op
        again = await writes.delete_customer_note(nid)
        assert again.get("no_change") is True
    finally:
        await close_pool()
