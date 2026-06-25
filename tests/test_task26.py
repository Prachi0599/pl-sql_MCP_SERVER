"""
TASK 26 — Web UI (Starlette app + ChatSession conversation engine).

Unit tests (no DB / no OpenAI): T26-01 .. T26-12
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.web.session import ChatSession


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_t26_01_find_write_detects_pending_and_no_change():
    s = ChatSession()
    pend = {"result": {"result": {"request_id": 5, "status": "PENDING",
                                  "summary": "x", "action": "update_account_status"}}}
    kind, leaf = s._find_write(pend)
    assert kind == "pending" and leaf["request_id"] == 5

    noop = {"result": {"no_change": True, "status": "NO_CHANGE", "message": "already X"}}
    kind, leaf = s._find_write(noop)
    assert kind == "no_change"


def test_t26_02_onboarding_steps_detection():
    s = ChatSession()
    leaf = {"total_steps": 5, "customer_number": "CUST-1", "steps": [
        {"request_id": 1, "status": "PENDING", "description": "Create customer"},
        {"request_id": 2, "status": "PENDING", "description": "Add address"}]}
    steps = s._onboarding_steps(leaf)
    assert steps and len(steps) == 2 and steps[0]["request_id"] == 1
    assert s._onboarding_steps({"data": []}) is None


def test_t26_03_confirmation_text_before_after_and_warning():
    s = ChatSession()
    t = s._confirmation_text({"action": "update_account_status",
                              "current_value": "ACTIVE", "requested_value": "INACTIVE"})
    assert "ACTIVE" in t and "INACTIVE" in t
    t2 = s._confirmation_text({"action": "delete_account", "warning": "Hard delete"})
    assert "Hard delete" in t2


def test_t26_04_pick_action_index_and_reco_request():
    s = ChatSession()
    s.last_context = {"customer_number": "CUST000122",
                      "recommended_actions": ["Chase invoice", "Open ticket"],
                      "rca_summary": "unpaid"}
    assert s._pick_action_index("apply recommendation 2", 2) == 2
    assert s._pick_action_index("apply the second one", 2) == 2
    assert s._pick_action_index("apply all", 2) == 0
    req = s._reco_followup_request("apply recommendation 1")
    assert "CUST000122" in req and "Chase invoice" in req


def test_t26_05_session_change_recap_format():
    s = ChatSession()
    assert "haven't applied any changes" in s._format_session_changes()
    s._record_change(101, "account status: 'ACTIVE' -> 'INACTIVE'")
    out = s._format_session_changes()
    assert "request #101" in out and "INACTIVE" in out


def test_t26_06_out_shape_signals_pending_buttons():
    s = ChatSession()
    s.pending = {"kind": "single", "request_id": 9, "desc": "update", "leaf": {}}
    out = s._out("prepared", "pending")
    assert out["kind"] == "pending" and out["pending"]["steps"] == 1
    s.pending = {"kind": "batch", "label": "onboarding", "steps": [1, 2, 3]}
    out = s._out("prepared", "pending")
    assert out["pending"]["steps"] == 3


# ── approval resolution (async, mocked DB) ────────────────────────────────────

@pytest.mark.asyncio
async def test_t26_07_resolve_single_approve_records_change():
    s = ChatSession()
    s.pending = {"kind": "single", "request_id": 9, "desc": "update account status",
                 "leaf": {"current_value": "ACTIVE", "requested_value": "INACTIVE"}}
    ok = {"success": True, "rows_affected": 1,
          "change_summary": "update account status: 'ACTIVE' -> 'INACTIVE' (1 row changed)",
          "dml_result": {}}
    with patch("src.tools.approval.approve_request",
               new_callable=AsyncMock, return_value=ok):
        out = await s._resolve(True)
    assert out["kind"] == "applied" and "INACTIVE" in out["reply"]
    assert s.pending is None and len(s.session_changes) == 1


@pytest.mark.asyncio
async def test_t26_08_resolve_single_reject():
    s = ChatSession()
    s.pending = {"kind": "single", "request_id": 9, "desc": "x", "leaf": {}}
    with patch("src.tools.approval.reject_request",
               new_callable=AsyncMock, return_value={"success": True}):
        out = await s._resolve(False)
    assert out["kind"] == "rejected" and "no changes" in out["reply"].lower()


@pytest.mark.asyncio
async def test_t26_09_resolve_batch_approves_all_steps():
    s = ChatSession()
    s.pending = {"kind": "batch", "label": "onboarding", "steps": [
        {"request_id": 1, "description": "Create customer"},
        {"request_id": 2, "description": "Add address"}]}
    with patch("src.tools.approval.approve_request",
               new_callable=AsyncMock, return_value={"success": True}):
        out = await s._resolve(True)
    assert out["kind"] == "applied" and "applied 2 of 2" in out["reply"]
    assert len(s.session_changes) == 2


# ── HTTP app (Starlette TestClient, ChatSession.send patched) ─────────────────

def test_t26_10_health_endpoint():
    from starlette.testclient import TestClient
    from src.web.app import app
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_t26_11_index_serves_html():
    from starlette.testclient import TestClient
    from src.web.app import app
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200 and "TCL Finance" in r.text


def test_t26_12_message_endpoint_routes_to_session():
    from starlette.testclient import TestClient
    from src.web.app import app
    fake = {"reply": "hi", "kind": "answer", "pending": None, "actions": None}
    with patch.object(ChatSession, "send", new_callable=AsyncMock, return_value=fake):
        with TestClient(app) as client:
            r = client.post("/api/message",
                            json={"session_id": "t", "text": "hello"})
    assert r.status_code == 200 and r.json()["reply"] == "hi"
