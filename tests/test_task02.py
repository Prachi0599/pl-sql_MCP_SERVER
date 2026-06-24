"""
TASK 02 — Python Project Scaffold & Oracle Connection
Unit tests: T02-01 through T02-10
"""
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── T02-04: .env variables load correctly ────────────────────────────────────

def test_t02_04_env_variables_load(tmp_path):
    """All 4 required env variables must be loadable from .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DB_USER=MCP_APP\n"
        "DB_PASSWORD=mcp123\n"
        "DB_CONNECT_STRING=localhost:1521/FREEPDB1\n"
        "OPENAI_API_KEY=sk-test-key\n"
    )
    from dotenv import dotenv_values
    vals = dotenv_values(str(env_file))
    assert vals["DB_USER"] == "MCP_APP"
    assert vals["DB_PASSWORD"] == "mcp123"
    assert vals["DB_CONNECT_STRING"] == "localhost:1521/FREEPDB1"
    assert vals["OPENAI_API_KEY"] == "sk-test-key"


# ── T02-07: ORA-00001 maps to "Duplicate value already exists" ───────────────

def test_t02_07_ora_00001_duplicate():
    from src.utils.errors import _ERROR_MAP
    assert _ERROR_MAP[1] == "Duplicate value already exists"


# ── T02-08: ORA-02291 maps to "Referenced entity does not exist" ─────────────

def test_t02_08_ora_02291_reference():
    from src.utils.errors import _ERROR_MAP
    assert _ERROR_MAP[2291] == "Referenced entity does not exist"


# ── T02-09: ORA-01400 maps to "Required field cannot be empty" ───────────────

def test_t02_09_ora_01400_empty():
    from src.utils.errors import _ERROR_MAP
    assert _ERROR_MAP[1400] == "Required field cannot be empty"


# ── T02-07/08/09 (extended): map_oracle_error returns correct structure ───────

def test_map_oracle_error_non_db_exception():
    from src.utils.errors import map_oracle_error
    result = map_oracle_error(RuntimeError("unexpected failure"))
    assert result["success"] is False
    assert result["error_code"] == "INTERNAL_ERROR"
    assert "unexpected failure" in result["message"]


# ── T02-06: audit.py DB failure does NOT crash the caller ────────────────────

@pytest.mark.asyncio
async def test_t02_06_audit_failure_non_fatal():
    """When the DB is unreachable, log_audit must swallow the exception and return False."""
    with patch("src.utils.audit.get_connection", side_effect=Exception("DB connection refused")):
        from src.utils.audit import log_audit
        result = await log_audit(
            "test_tool", "TEST_PKG", "TEST_PROC",
            "READ", {"param": "value"}, "STARTED",
        )
    assert result is False


# ── T02-10: MCP server module imports and FastMCP instance created ────────────

def test_t02_10_server_instantiates():
    """server.py must import cleanly and expose a FastMCP instance named 'mcp'."""
    from src.server import mcp
    assert mcp is not None
    assert mcp.name == "tcl-finance-billing"


# ── T02-01: get_connection() returns valid Oracle connection (integration) ────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t02_01_get_connection_valid():
    import oracledb
    from src.db.pool import get_connection, close_pool
    try:
        conn = await get_connection()
        assert conn is not None
        with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM DUAL")
            row = await cur.fetchone()
        assert row is not None and row[0] == 1
        await conn.close()
    except (oracledb.OperationalError, oracledb.DatabaseError, OSError) as exc:
        pytest.skip(f"Oracle DB unavailable: {exc}")
    finally:
        await close_pool()


# ── T02-02: pool never exceeds max=10 connections ────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t02_02_pool_max_connections():
    import oracledb
    from src.db.pool import get_pool, get_connection, close_pool
    try:
        pool = get_pool()
        # These properties are set synchronously at pool creation
        assert pool.max == 10
        assert pool.min == 2
        conn = await get_connection()
        await conn.close()
    except (oracledb.OperationalError, oracledb.DatabaseError,
            oracledb.InterfaceError, OSError) as exc:
        pytest.skip(f"Oracle DB unavailable: {exc}")
    finally:
        await close_pool()


# ── T02-03: close_pool() completes cleanly (simulates SIGINT) ────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t02_03_close_pool_sigint():
    """Pool is set to None after close_pool() — regardless of Oracle availability."""
    from src.db import pool as pool_mod
    from src.db.pool import get_pool, close_pool
    get_pool()
    assert pool_mod._pool is not None
    await close_pool()  # force=True so it always succeeds
    assert pool_mod._pool is None


# ── T02-05: log_audit inserts row into MCP_AUDIT_LOG (integration) ───────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t02_05_audit_inserts_row():
    import oracledb
    from src.db.pool import get_connection, close_pool
    from src.utils.audit import log_audit
    try:
        conn = await get_connection()
    except (oracledb.OperationalError, oracledb.DatabaseError, OSError) as exc:
        pytest.skip(f"Oracle DB unavailable: {exc}")
        return

    try:
        with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM MCP_AUDIT_LOG")
            count_before = (await cur.fetchone())[0]
        await conn.close()

        ok = await log_audit(
            "test_tool_t02_05", "MCP_SECURITY_PKG", "LOG_AUDIT",
            "READ", {"test": True}, "SUCCESS",
        )
        assert ok is True

        conn2 = await get_connection()
        with conn2.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM MCP_AUDIT_LOG WHERE TOOL_NAME = 'test_tool_t02_05'"
            )
            count_after = (await cur.fetchone())[0]
        await conn2.close()

        assert count_after > 0
    finally:
        await close_pool()
