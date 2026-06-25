"""Starlette web app for the TCL Finance & Billing assistant.

Serves a single-page chat UI (static/index.html) and a small JSON API backed by
ChatSession. Run it with:

    python web.py                 # convenience launcher (uvicorn)
    uvicorn src.web.app:app       # or directly

Endpoints:
    GET  /                 → the chat UI
    POST /api/message      → {session_id, text} -> ChatSession.send() result
    POST /api/reset        → {session_id} -> clears a session
    GET  /api/health       → liveness probe
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

load_dotenv()

from src.db.pool import close_pool          # noqa: E402
from src.web.session import ChatSession      # noqa: E402

_STATIC = os.path.join(os.path.dirname(__file__), "static")

# In-memory session store (single-process local app). Each browser tab sends a
# stable session_id; we keep one ChatSession per id.
_SESSIONS: dict[str, ChatSession] = {}


def _session(session_id: str) -> ChatSession:
    sid = session_id or "default"
    if sid not in _SESSIONS:
        _SESSIONS[sid] = ChatSession()
    return _SESSIONS[sid]


async def index(request):
    return FileResponse(os.path.join(_STATIC, "index.html"))


async def message(request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"reply": "Bad request.", "kind": "error",
                             "pending": None, "actions": None}, status_code=400)
    text = (body.get("text") or "").strip()
    sess = _session(body.get("session_id"))
    result = await sess.send(text)
    return JSONResponse(result)


async def reset(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    sid = body.get("session_id") or "default"
    _SESSIONS.pop(sid, None)
    return JSONResponse({"ok": True})


async def health(request):
    return JSONResponse({"ok": True, "sessions": len(_SESSIONS)})


@asynccontextmanager
async def _lifespan(app):
    yield
    await close_pool()


app = Starlette(
    debug=False,
    routes=[
        Route("/", index, methods=["GET"]),
        Route("/api/message", message, methods=["POST"]),
        Route("/api/reset", reset, methods=["POST"]),
        Route("/api/health", health, methods=["GET"]),
    ],
    lifespan=_lifespan,
)
