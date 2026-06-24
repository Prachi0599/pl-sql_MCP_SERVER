import oracledb

_ERROR_MAP: dict[int, str] = {
    1: "Duplicate value already exists",
    54: "Resource busy — row locked by another session",
    1400: "Required field cannot be empty",
    1403: "No data found",
    1422: "Query returned more than one row",
    2291: "Referenced entity does not exist",
    2292: "Cannot delete — child records exist",
    20001: "Approval request already processed",
    20002: "Approval request not found",
    20003: "Invalid status transition",
}


def map_oracle_error(exc: Exception) -> dict:
    if isinstance(exc, oracledb.DatabaseError):
        error_obj = exc.args[0]
        code = getattr(error_obj, "code", 0)
        message = _ERROR_MAP.get(code)
        if message is None:
            message = getattr(error_obj, "message", str(exc))
        return {
            "success": False,
            "error_code": f"ORA-{code:05d}",
            "message": message,
        }
    return {
        "success": False,
        "error_code": "INTERNAL_ERROR",
        "message": str(exc),
    }
