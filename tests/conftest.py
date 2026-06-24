"""Shared pytest fixtures and configuration."""
import os
import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv()

# ── markers ──────────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires live Oracle DB")


def pytest_collection_modifyitems(config, items):
    skip_integration = pytest.mark.skip(reason="Oracle DB not reachable — set DB_* env vars")
    db_available = bool(os.getenv("DB_USER") and os.getenv("DB_CONNECT_STRING"))
    for item in items:
        if "integration" in item.keywords and not db_available:
            item.add_marker(skip_integration)


# ── DB fixture ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def db_conn():
    """Yield one Oracle connection per test; skip if DB unavailable."""
    from src.db.pool import get_connection, close_pool
    conn = None
    try:
        conn = await get_connection()
        yield conn
    except Exception as exc:
        pytest.skip(f"Oracle DB unavailable: {exc}")
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
        await close_pool()
