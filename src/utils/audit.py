import json
import logging
from src.db.pool import get_connection

logger = logging.getLogger(__name__)


async def log_audit(
    tool_name: str,
    package_name: str,
    procedure_name: str,
    action_type: str,
    request_payload: dict,
    status: str,
    error_message: str | None = None,
) -> bool:
    """Call MCP_SECURITY_PKG.LOG_AUDIT. Never raises — audit failures are non-fatal."""
    try:
        conn = await get_connection()
        try:
            with conn.cursor() as cur:
                await cur.callproc(
                    "MCP_SECURITY_PKG.LOG_AUDIT",
                    [
                        tool_name,
                        package_name,
                        procedure_name,
                        action_type,
                        json.dumps(request_payload),
                        status,
                        error_message,
                    ],
                )
            # AUTONOMOUS_TRANSACTION commits independently, but commit here for safety
            await conn.commit()
        finally:
            await conn.close()
        return True
    except Exception as exc:
        logger.warning("Audit log failed (non-fatal): %s", exc)
        return False
