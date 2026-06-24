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


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None:
        try:
            await _pool.close(force=True)
        except Exception:
            pass
        _pool = None
        _pool_loop = None
