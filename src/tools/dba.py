"""Group N — DBA / Database-Administration tools.

Read diagnostics (no approval needed):
    get_database_health        — one-shot health snapshot
    get_active_sessions        — current sessions (needs V$ access)
    get_blocking_sessions      — blocking locks / deadlock risk (needs V$ access)
    get_slow_queries           — top SQL by elapsed time (needs V$ access)
    get_wait_events            — top system wait events (needs V$ access)
    get_tablespace_usage       — tablespace / segment space usage
    get_segment_sizes          — largest segments in the schema
    get_invalid_objects        — INVALID packages/procedures/views
    get_unused_indexes         — secondary indexes to review for removal
    get_redundant_indexes      — indexes whose columns prefix another index
    get_table_stats_status     — tables with stale / missing optimizer stats
    get_long_operations        — long-running operations in progress

Maintenance writes (approval-gated, run only after approve_request):
    drop_index                 — DROP a non-constraint index
    rebuild_index              — ALTER INDEX ... REBUILD
    gather_table_stats         — DBMS_STATS.GATHER_TABLE_STATS
    recompile_object           — ALTER ... COMPILE an INVALID object

The MCP_APP application account does NOT have access to the V$ dynamic
performance views by default. Any tool that needs them degrades to a clear,
actionable message (grant `SELECT_CATALOG_ROLE` — see sql/grant_dba_monitor.sql)
instead of raising. Tools that use USER_*/ALL_* dictionary views always work.
"""
from __future__ import annotations

import json
from typing import Any

import oracledb

from src.db.pool import get_connection
from src.tools.approval import create_approval_request
from src.utils.audit import log_audit
from src.utils.errors import map_oracle_error

_TOOL = "dba"
_SCHEMA = "MCP_APP"
_LIMIT_DEFAULT = 20
_LIMIT_MAX = 200

_PRIV_HINT = (
    "This metric needs the Oracle V$ dynamic performance views, which the "
    "application account (MCP_APP) cannot read by default. Ask a DBA to run "
    "sql/grant_dba_monitor.sql (grants SELECT_CATALOG_ROLE) to enable it."
)


async def _exec(conn: oracledb.AsyncConnection, sql: str,
                params: list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [d[0].lower() for d in cur.description]
        rows = await cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _clamp(n: int) -> int:
    return min(max(1, int(n or _LIMIT_DEFAULT)), _LIMIT_MAX)


def _ok(data: Any, row_count: int | None = None, **extra: Any) -> dict:
    r: dict = {"success": True, "data": data, **extra}
    if row_count is not None:
        r["row_count"] = row_count
    return r


def _is_missing_view(exc: Exception) -> bool:
    """True for ORA-00942 (table/view does not exist) — i.e. a privilege gap on
    a V$ view rather than a real error."""
    return "ORA-00942" in str(exc)


def _priv_degraded(metric: str) -> dict:
    """A successful response that simply could not be computed due to missing
    catalog privileges — surfaced clearly rather than as a hard error."""
    return {"success": True, "available": False, "metric": metric,
            "data": None, "message": _PRIV_HINT}


# ── N1: get_database_health ───────────────────────────────────────────────────

async def get_database_health() -> dict:
    """One-shot health snapshot built entirely from accessible dictionary views.

    Reports: DB version, schema object counts, INVALID object count, total
    schema size, index/table counts, count of tables with stale/missing stats,
    and any long-running operations in progress."""
    conn = await get_connection()
    try:
        version = await _exec(conn,
            "SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
        invalid = await _exec(conn, f"""
            SELECT COUNT(*) AS cnt FROM ALL_OBJECTS
            WHERE OWNER = '{_SCHEMA}' AND STATUS = 'INVALID'
        """)
        objs = await _exec(conn, f"""
            SELECT OBJECT_TYPE, COUNT(*) AS cnt
            FROM ALL_OBJECTS WHERE OWNER = '{_SCHEMA}'
            GROUP BY OBJECT_TYPE ORDER BY OBJECT_TYPE
        """)
        size = await _exec(conn,
            "SELECT ROUND(SUM(BYTES)/1048576, 2) AS mb, COUNT(*) AS segs "
            "FROM USER_SEGMENTS")
        stale = await _exec(conn, """
            SELECT COUNT(*) AS cnt FROM USER_TABLES
            WHERE NUM_ROWS IS NULL OR LAST_ANALYZED IS NULL
               OR LAST_ANALYZED < SYSDATE - 30
        """)
        longops = await _exec(conn, """
            SELECT COUNT(*) AS cnt FROM V$SESSION_LONGOPS
            WHERE TIME_REMAINING > 0
        """)
        health = {
            "database_version": version[0]["banner"] if version else None,
            "schema": _SCHEMA,
            "invalid_object_count": invalid[0]["cnt"] if invalid else 0,
            "object_counts": {o["object_type"]: o["cnt"] for o in objs},
            "schema_size_mb": (size[0]["mb"] if size else 0) or 0,
            "segment_count": (size[0]["segs"] if size else 0) or 0,
            "tables_with_stale_stats": stale[0]["cnt"] if stale else 0,
            "long_running_operations": longops[0]["cnt"] if longops else 0,
            "status": "HEALTHY"
                      if (invalid and invalid[0]["cnt"] == 0) else "ATTENTION",
        }
        await log_audit(_TOOL, "", "get_database_health", "READ", {}, "SUCCESS")
        return _ok(health)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_database_health", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N2: get_active_sessions (V$) ──────────────────────────────────────────────

async def get_active_sessions(limit: int = _LIMIT_DEFAULT) -> dict:
    """Return current non-background sessions (needs V$SESSION access)."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT SID, SERIAL# AS serial_no, USERNAME, STATUS,
                   OSUSER, MACHINE, PROGRAM, SQL_ID,
                   TO_CHAR(LOGON_TIME, 'YYYY-MM-DD HH24:MI:SS') AS logon_time
            FROM   V$SESSION
            WHERE  TYPE = 'USER'
            ORDER BY STATUS, LOGON_TIME
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        await log_audit(_TOOL, "", "get_active_sessions", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        if _is_missing_view(exc):
            await log_audit(_TOOL, "", "get_active_sessions", "READ", {},
                            "SUCCESS")
            return _priv_degraded("active_sessions")
        await log_audit(_TOOL, "", "get_active_sessions", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N3: get_blocking_sessions (V$) ────────────────────────────────────────────

async def get_blocking_sessions() -> dict:
    """Return sessions blocking others (lock contention / deadlock risk).
    Needs V$ access; degrades gracefully otherwise."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT b.SID         AS blocker_sid,
                   w.SID         AS waiter_sid,
                   bs.SERIAL#    AS blocker_serial,
                   bs.USERNAME   AS blocker_user,
                   ws.USERNAME   AS waiter_user,
                   ws.SECONDS_IN_WAIT AS waiter_seconds
            FROM   V$LOCK b
            JOIN   V$LOCK w   ON b.ID1 = w.ID1 AND b.ID2 = w.ID2
                             AND b.BLOCK = 1 AND w.REQUEST > 0
            JOIN   V$SESSION bs ON bs.SID = b.SID
            JOIN   V$SESSION ws ON ws.SID = w.SID
            ORDER BY waiter_seconds DESC
        """)
        await log_audit(_TOOL, "", "get_blocking_sessions", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows),
                   blocking_detected=len(rows) > 0)
    except Exception as exc:
        if _is_missing_view(exc):
            await log_audit(_TOOL, "", "get_blocking_sessions", "READ", {},
                            "SUCCESS")
            return _priv_degraded("blocking_sessions")
        await log_audit(_TOOL, "", "get_blocking_sessions", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N4: get_slow_queries (V$) ─────────────────────────────────────────────────

async def get_slow_queries(limit: int = 10) -> dict:
    """Return the top SQL statements by average elapsed time per execution
    (query-optimization candidates). Needs V$SQL access."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT SQL_ID,
                   ROUND(ELAPSED_TIME/1e6, 3)              AS total_elapsed_sec,
                   EXECUTIONS,
                   ROUND(ELAPSED_TIME/GREATEST(EXECUTIONS,1)/1e6, 4) AS avg_sec_per_exec,
                   BUFFER_GETS, DISK_READS,
                   SUBSTR(SQL_TEXT, 1, 200)                AS sql_text
            FROM   V$SQL
            WHERE  EXECUTIONS > 0
            ORDER BY ELAPSED_TIME/GREATEST(EXECUTIONS,1) DESC
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        await log_audit(_TOOL, "", "get_slow_queries", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        if _is_missing_view(exc):
            await log_audit(_TOOL, "", "get_slow_queries", "READ", {}, "SUCCESS")
            return _priv_degraded("slow_queries")
        await log_audit(_TOOL, "", "get_slow_queries", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N5: get_wait_events (V$) ──────────────────────────────────────────────────

async def get_wait_events(limit: int = 15) -> dict:
    """Return top system wait events by total time waited. Needs V$ access."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT EVENT, TOTAL_WAITS, TOTAL_TIMEOUTS,
                   ROUND(TIME_WAITED/100, 2) AS time_waited_sec,
                   WAIT_CLASS
            FROM   V$SYSTEM_EVENT
            WHERE  WAIT_CLASS <> 'Idle'
            ORDER BY TIME_WAITED DESC
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        await log_audit(_TOOL, "", "get_wait_events", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        if _is_missing_view(exc):
            await log_audit(_TOOL, "", "get_wait_events", "READ", {}, "SUCCESS")
            return _priv_degraded("wait_events")
        await log_audit(_TOOL, "", "get_wait_events", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N6: get_tablespace_usage ──────────────────────────────────────────────────

async def get_tablespace_usage() -> dict:
    """Return space used per tablespace. Tries the DBA metric view, then
    degrades to a per-tablespace roll-up of this schema's own segments."""
    conn = await get_connection()
    try:
        try:
            rows = await _exec(conn, """
                SELECT TABLESPACE_NAME,
                       ROUND(USED_SPACE * 8 / 1024, 2)  AS used_mb,
                       ROUND(TABLESPACE_SIZE * 8 / 1024, 2) AS size_mb,
                       ROUND(USED_PERCENT, 2)           AS used_percent
                FROM   DBA_TABLESPACE_USAGE_METRICS
                ORDER BY USED_PERCENT DESC
            """)
            source = "DBA_TABLESPACE_USAGE_METRICS"
        except Exception as inner:
            if not _is_missing_view(inner):
                raise
            rows = await _exec(conn, """
                SELECT TABLESPACE_NAME,
                       ROUND(SUM(BYTES)/1048576, 2) AS used_mb,
                       COUNT(*)                     AS segment_count
                FROM   USER_SEGMENTS
                GROUP BY TABLESPACE_NAME
                ORDER BY used_mb DESC
            """)
            source = "USER_SEGMENTS (schema-only roll-up; full view needs DBA grant)"
        await log_audit(_TOOL, "", "get_tablespace_usage", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows), source=source)
    except Exception as exc:
        await log_audit(_TOOL, "", "get_tablespace_usage", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N7: get_segment_sizes ─────────────────────────────────────────────────────

async def get_segment_sizes(limit: int = _LIMIT_DEFAULT) -> dict:
    """Return the largest segments (tables/indexes) owned by the schema."""
    limit = _clamp(limit)
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT SEGMENT_NAME, SEGMENT_TYPE,
                   ROUND(BYTES/1048576, 2) AS size_mb, BLOCKS, EXTENTS
            FROM   USER_SEGMENTS
            ORDER BY BYTES DESC
            FETCH FIRST :1 ROWS ONLY
        """, [limit])
        await log_audit(_TOOL, "", "get_segment_sizes", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_segment_sizes", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N8: get_invalid_objects ───────────────────────────────────────────────────

async def get_invalid_objects() -> dict:
    """Return INVALID objects in the schema (need recompilation)."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, f"""
            SELECT OBJECT_NAME, OBJECT_TYPE, STATUS,
                   TO_CHAR(LAST_DDL_TIME, 'YYYY-MM-DD HH24:MI:SS') AS last_ddl_time
            FROM   ALL_OBJECTS
            WHERE  OWNER = '{_SCHEMA}' AND STATUS = 'INVALID'
            ORDER BY OBJECT_TYPE, OBJECT_NAME
        """)
        await log_audit(_TOOL, "", "get_invalid_objects", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_invalid_objects", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N9: get_unused_indexes ────────────────────────────────────────────────────

async def get_unused_indexes() -> dict:
    """Return secondary (non-constraint) indexes that are candidates for review
    or removal — i.e. indexes NOT backing a primary-key/unique constraint.

    Note: Oracle cannot prove an index is unused without monitoring enabled, so
    these are *review candidates*: dropping a genuinely unused secondary index
    reclaims space and speeds up DML. Constraint-backing indexes are excluded
    because dropping them would break the constraint."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT i.INDEX_NAME, i.TABLE_NAME, i.UNIQUENESS, i.INDEX_TYPE,
                   i.NUM_ROWS, i.DISTINCT_KEYS,
                   TO_CHAR(i.LAST_ANALYZED, 'YYYY-MM-DD') AS last_analyzed,
                   LISTAGG(c.COLUMN_NAME, ', ')
                     WITHIN GROUP (ORDER BY c.COLUMN_POSITION) AS columns
            FROM   USER_INDEXES i
            JOIN   USER_IND_COLUMNS c ON c.INDEX_NAME = i.INDEX_NAME
            WHERE  i.INDEX_NAME NOT IN (
                       SELECT INDEX_NAME FROM USER_CONSTRAINTS
                       WHERE INDEX_NAME IS NOT NULL)
              AND  i.UNIQUENESS = 'NONUNIQUE'
            GROUP BY i.INDEX_NAME, i.TABLE_NAME, i.UNIQUENESS, i.INDEX_TYPE,
                     i.NUM_ROWS, i.DISTINCT_KEYS, i.LAST_ANALYZED
            ORDER BY i.TABLE_NAME, i.INDEX_NAME
        """)
        await log_audit(_TOOL, "", "get_unused_indexes", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows),
                   note="Review candidates (non-constraint secondary indexes). "
                        "Use drop_index to remove one after approval.")
    except Exception as exc:
        await log_audit(_TOOL, "", "get_unused_indexes", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N10: get_redundant_indexes ────────────────────────────────────────────────

async def get_redundant_indexes() -> dict:
    """Return indexes whose leading columns are a prefix of another index on the
    same table (the shorter one is usually redundant)."""
    conn = await get_connection()
    try:
        idx = await _exec(conn, """
            SELECT i.TABLE_NAME, i.INDEX_NAME,
                   LISTAGG(c.COLUMN_NAME, ',')
                     WITHIN GROUP (ORDER BY c.COLUMN_POSITION) AS cols
            FROM   USER_INDEXES i
            JOIN   USER_IND_COLUMNS c ON c.INDEX_NAME = i.INDEX_NAME
            GROUP BY i.TABLE_NAME, i.INDEX_NAME
            ORDER BY i.TABLE_NAME
        """)
        by_table: dict[str, list[dict]] = {}
        for r in idx:
            by_table.setdefault(r["table_name"], []).append(r)

        redundant: list[dict] = []
        for table, indexes in by_table.items():
            for a in indexes:
                for b in indexes:
                    if a["index_name"] == b["index_name"]:
                        continue
                    # a is redundant if its column list is a prefix of b's
                    if (b["cols"] + ",").startswith(a["cols"] + ",") \
                            and len(a["cols"]) < len(b["cols"]):
                        redundant.append({
                            "table_name": table,
                            "redundant_index": a["index_name"],
                            "redundant_columns": a["cols"],
                            "superseded_by": b["index_name"],
                            "superset_columns": b["cols"],
                        })
        await log_audit(_TOOL, "", "get_redundant_indexes", "READ", {}, "SUCCESS")
        return _ok(redundant, len(redundant))
    except Exception as exc:
        await log_audit(_TOOL, "", "get_redundant_indexes", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N11: get_table_stats_status ───────────────────────────────────────────────

async def get_table_stats_status() -> dict:
    """Return tables with missing or stale optimizer statistics, with the volume
    of DML since the last analyze (gather-stats candidates)."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT t.TABLE_NAME, t.NUM_ROWS,
                   TO_CHAR(t.LAST_ANALYZED, 'YYYY-MM-DD HH24:MI') AS last_analyzed,
                   NVL(m.INSERTS,0) AS inserts,
                   NVL(m.UPDATES,0) AS updates,
                   NVL(m.DELETES,0) AS deletes,
                   CASE
                     WHEN t.LAST_ANALYZED IS NULL OR t.NUM_ROWS IS NULL THEN 'MISSING'
                     WHEN t.LAST_ANALYZED < SYSDATE - 30 THEN 'STALE_AGE'
                     WHEN NVL(m.INSERTS,0)+NVL(m.UPDATES,0)+NVL(m.DELETES,0)
                          > GREATEST(t.NUM_ROWS,1) * 0.10 THEN 'STALE_DML'
                     ELSE 'OK'
                   END AS stats_status
            FROM   USER_TABLES t
            LEFT JOIN USER_TAB_MODIFICATIONS m ON m.TABLE_NAME = t.TABLE_NAME
            ORDER BY stats_status, t.TABLE_NAME
        """)
        candidates = [r for r in rows if r["stats_status"] != "OK"]
        await log_audit(_TOOL, "", "get_table_stats_status", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows),
                   gather_candidates=[r["table_name"] for r in candidates])
    except Exception as exc:
        await log_audit(_TOOL, "", "get_table_stats_status", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ── N12: get_long_operations ──────────────────────────────────────────────────

async def get_long_operations() -> dict:
    """Return long-running operations currently in progress (full scans, sorts,
    stats gathers) — a common cause of perceived slowdown."""
    conn = await get_connection()
    try:
        rows = await _exec(conn, """
            SELECT SID, SERIAL# AS serial_no, OPNAME, TARGET,
                   ROUND(SOFAR/GREATEST(TOTALWORK,1)*100, 1) AS percent_done,
                   TIME_REMAINING AS seconds_remaining, ELAPSED_SECONDS,
                   TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS start_time
            FROM   V$SESSION_LONGOPS
            WHERE  TIME_REMAINING > 0
            ORDER BY TIME_REMAINING DESC
        """)
        await log_audit(_TOOL, "", "get_long_operations", "READ", {}, "SUCCESS")
        return _ok(rows, len(rows))
    except Exception as exc:
        if _is_missing_view(exc):
            return _priv_degraded("long_operations")
        await log_audit(_TOOL, "", "get_long_operations", "READ", {},
                        "ERROR", str(exc))
        return map_oracle_error(exc)
    finally:
        await conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Maintenance WRITES — staged through the standard approval workflow.
# Nothing executes until approve_request(request_id) runs the stored statement.
# ════════════════════════════════════════════════════════════════════════════

def _validation_error(message: str) -> dict:
    return {"success": False, "error_code": "VALIDATION_ERROR", "message": message}


def _no_change_msg(message: str, **extra: Any) -> dict:
    return {"success": True, "no_change": True, "status": "NO_CHANGE",
            "message": message, **extra}


async def _index_meta(conn: oracledb.AsyncConnection, index_name: str) -> dict | None:
    rows = await _exec(conn, """
        SELECT i.INDEX_NAME, i.TABLE_NAME, i.UNIQUENESS,
               (SELECT COUNT(*) FROM USER_CONSTRAINTS
                WHERE INDEX_NAME = i.INDEX_NAME) AS backs_constraint
        FROM   USER_INDEXES i
        WHERE  i.INDEX_NAME = :1
    """, [index_name.upper()])
    return rows[0] if rows else None


async def drop_index(index_name: str, requested_by: str = "mcp_user") -> dict:
    """Stage a DROP INDEX after approval. Refuses to drop an index that backs a
    primary-key/unique constraint (would break the constraint)."""
    if not index_name or not index_name.strip():
        return _validation_error("index_name is required")
    conn = await get_connection()
    try:
        meta = await _index_meta(conn, index_name)
        if meta is None:
            return _no_change_msg(
                f"Index '{index_name.upper()}' does not exist in {_SCHEMA} - "
                f"nothing to drop.")
        if meta["backs_constraint"] > 0 or meta["uniqueness"] == "UNIQUE":
            return _validation_error(
                f"Index '{meta['index_name']}' backs a unique/primary-key "
                f"constraint and cannot be dropped directly. Drop or disable the "
                f"constraint instead.")

        idx = meta["index_name"]
        new_val = json.dumps({"sql": f'DROP INDEX {_SCHEMA}."{idx}"', "params": []})
        req = await create_approval_request(
            conn, package_name="DIRECT_SQL", procedure_name="DROP_INDEX",
            action_type="DELETE",
            old_value=json.dumps({"index_name": idx, "table_name": meta["table_name"]}),
            new_value=new_val, requested_by=requested_by)
        await log_audit(_TOOL, "", "drop_index", "DELETE",
                        {"index_name": idx}, "SUCCESS")
        return {"success": True, **req, "index_name": idx,
                "table_name": meta["table_name"]}
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def rebuild_index(index_name: str, requested_by: str = "mcp_user") -> dict:
    """Stage an ALTER INDEX ... REBUILD after approval (defragment / re-cluster)."""
    if not index_name or not index_name.strip():
        return _validation_error("index_name is required")
    conn = await get_connection()
    try:
        meta = await _index_meta(conn, index_name)
        if meta is None:
            return _no_change_msg(
                f"Index '{index_name.upper()}' does not exist in {_SCHEMA}.")
        idx = meta["index_name"]
        new_val = json.dumps(
            {"sql": f'ALTER INDEX {_SCHEMA}."{idx}" REBUILD', "params": []})
        req = await create_approval_request(
            conn, package_name="DIRECT_SQL", procedure_name="REBUILD_INDEX",
            action_type="UPDATE", old_value=json.dumps({"index_name": idx}),
            new_value=new_val, requested_by=requested_by)
        await log_audit(_TOOL, "", "rebuild_index", "UPDATE",
                        {"index_name": idx}, "SUCCESS")
        return {"success": True, **req, "index_name": idx}
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def gather_table_stats(table_name: str,
                             requested_by: str = "mcp_user") -> dict:
    """Stage a DBMS_STATS.GATHER_TABLE_STATS for a table after approval."""
    if not table_name or not table_name.strip():
        return _validation_error("table_name is required")
    conn = await get_connection()
    try:
        tbl = table_name.upper()
        exists = await _exec(conn,
            "SELECT TABLE_NAME FROM USER_TABLES WHERE TABLE_NAME = :1", [tbl])
        if not exists:
            return _no_change_msg(
                f"Table '{tbl}' does not exist in {_SCHEMA}.")
        new_val = json.dumps({
            "sql": ("BEGIN DBMS_STATS.GATHER_TABLE_STATS("
                    "ownname => :1, tabname => :2, cascade => TRUE); END;"),
            "params": [_SCHEMA, tbl],
        })
        req = await create_approval_request(
            conn, package_name="DIRECT_SQL", procedure_name="GATHER_TABLE_STATS",
            action_type="UPDATE", old_value=json.dumps({"table_name": tbl}),
            new_value=new_val, requested_by=requested_by)
        await log_audit(_TOOL, "", "gather_table_stats", "UPDATE",
                        {"table_name": tbl}, "SUCCESS")
        return {"success": True, **req, "table_name": tbl}
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()


async def recompile_object(object_name: str,
                           requested_by: str = "mcp_user") -> dict:
    """Stage an ALTER ... COMPILE for an INVALID object after approval."""
    if not object_name or not object_name.strip():
        return _validation_error("object_name is required")
    conn = await get_connection()
    try:
        obj = object_name.upper()
        rows = await _exec(conn, f"""
            SELECT OBJECT_NAME, OBJECT_TYPE, STATUS FROM ALL_OBJECTS
            WHERE OWNER = '{_SCHEMA}' AND OBJECT_NAME = :1
              AND OBJECT_TYPE IN ('PACKAGE','PACKAGE BODY','PROCEDURE',
                                  'FUNCTION','VIEW','TRIGGER')
            ORDER BY OBJECT_TYPE
        """, [obj])
        if not rows:
            return _no_change_msg(f"Object '{obj}' not found in {_SCHEMA}.")
        otype = rows[0]["object_type"]
        compile_type = "PACKAGE" if otype.startswith("PACKAGE") else otype
        new_val = json.dumps({
            "sql": f'ALTER {compile_type} {_SCHEMA}."{obj}" COMPILE',
            "params": [],
        })
        req = await create_approval_request(
            conn, package_name="DIRECT_SQL", procedure_name="RECOMPILE_OBJECT",
            action_type="UPDATE",
            old_value=json.dumps({"object_name": obj, "status": rows[0]["status"]}),
            new_value=new_val, requested_by=requested_by)
        await log_audit(_TOOL, "", "recompile_object", "UPDATE",
                        {"object_name": obj}, "SUCCESS")
        return {"success": True, **req, "object_name": obj, "object_type": otype}
    except Exception as exc:
        return map_oracle_error(exc)
    finally:
        await conn.close()
