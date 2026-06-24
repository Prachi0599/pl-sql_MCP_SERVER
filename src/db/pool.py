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


def get_pool() -> oracledb.AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool_async(
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            dsn=os.getenv("DB_CONNECT_STRING", ""),
            min=2,
            max=10,
            increment=1,
        )
    return _pool


async def get_connection() -> oracledb.AsyncConnection:
    pool = get_pool()
    return await pool.acquire()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close(force=True)
        except Exception:
            pass
        _pool = None
