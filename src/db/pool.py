import asyncio
import os
import oracledb
from dotenv import load_dotenv

load_dotenv()

# Fetch CLOB/BLOB columns as plain str/bytes instead of LOB locator objects.
# Without this, CLOB columns such as MCP_APPROVAL_REQUEST.NEW_VALUE come back as
# unread AsyncLOB objects — breaking JSON serialization in read tools and
# json.loads() during approval DML dispatch.
oracledb.defaults.fetch_lobs = False

_pool: oracledb.AsyncConnectionPool | None = None
# The event loop the pool was created on. An oracledb async pool is bound to the
# loop it was created on; reusing it from a different loop raises "bound to a
# different event loop". In production there is a single loop so this never
# changes; under pytest-asyncio (a fresh loop per test) it does, so we detect a
# loop change and transparently recreate the pool.
_pool_loop: asyncio.AbstractEventLoop | None = None

# Optional dedicated read-only pool, used by the SQL read agent so its generated
# queries run under a DB-enforced read-only account (SELECT-only privileges).
# Falls back to the main pool when DB_READONLY_USER is not configured.
_ro_pool: oracledb.AsyncConnectionPool | None = None
_ro_pool_loop: asyncio.AbstractEventLoop | None = None


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_pool() -> oracledb.AsyncConnectionPool:
    global _pool, _pool_loop
    loop = _current_loop()
    if (_pool is not None and _pool_loop is not None
            and loop is not None and _pool_loop is not loop):
        # Bound to a stale loop — abandon it (best effort) and recreate on this loop.
        try:
            _pool.close(force=True)
        except Exception:
            pass
        _pool = None
        _pool_loop = None
    if _pool is None:
        _pool = oracledb.create_pool_async(
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            dsn=os.getenv("DB_CONNECT_STRING", ""),
            min=2,
            max=10,
            increment=1,
        )
        _pool_loop = loop
    return _pool


async def get_connection() -> oracledb.AsyncConnection:
    pool = get_pool()
    return await pool.acquire()


def _readonly_configured() -> bool:
    return bool(os.getenv("DB_READONLY_USER"))


def get_readonly_pool() -> oracledb.AsyncConnectionPool | None:
    """Return the read-only pool, or None if no read-only user is configured."""
    global _ro_pool, _ro_pool_loop
    if not _readonly_configured():
        return None
    loop = _current_loop()
    if (_ro_pool is not None and _ro_pool_loop is not None
            and loop is not None and _ro_pool_loop is not loop):
        try:
            _ro_pool.close(force=True)
        except Exception:
            pass
        _ro_pool = None
        _ro_pool_loop = None
    if _ro_pool is None:
        _ro_pool = oracledb.create_pool_async(
            user=os.getenv("DB_READONLY_USER", ""),
            password=os.getenv("DB_READONLY_PASSWORD", ""),
            dsn=os.getenv("DB_CONNECT_STRING", ""),
            min=1,
            max=5,
            increment=1,
        )
        _ro_pool_loop = loop
    return _ro_pool


async def get_readonly_connection() -> oracledb.AsyncConnection:
    """Acquire a read-only connection. Falls back to the main (read/write) pool
    when no dedicated read-only user is configured (DB_READONLY_USER unset)."""
    pool = get_readonly_pool()
    if pool is None:
        return await get_connection()
    return await pool.acquire()


async def close_pool() -> None:
    global _pool, _pool_loop, _ro_pool, _ro_pool_loop
    for attr in ("_pool", "_ro_pool"):
        p = globals()[attr]
        if p is not None:
            try:
                await p.close(force=True)
            except Exception:
                pass
    _pool = None
    _pool_loop = None
    _ro_pool = None
    _ro_pool_loop = None
