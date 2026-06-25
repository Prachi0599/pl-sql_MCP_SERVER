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
    old = json.dumps({"account_number": "ACC1", "old_status": "ACTIVE"})
    new = json.dumps({"params": [10, "INACTIVE"]})
    s = _describe_change("UPDATE", old, new, "UPDATE_ACCOUNT_STATUS", 1)
    assert "ACTIVE" in s and "INACTIVE" in s and "1 row" in s


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
