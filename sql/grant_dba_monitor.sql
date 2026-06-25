-- ============================================================================
-- grant_dba_monitor.sql
--
-- OPTIONAL: enable the full set of DBA diagnostics for the application account.
--
-- The MCP_APP application user can already read the dictionary views the DBA
-- tools use for health, indexes, segments, statistics and long operations
-- (USER_*/ALL_* views + V$SESSION_LONGOPS). The remaining performance metrics —
-- active sessions, blocking/deadlocks, slow queries, and system wait events —
-- read the V$ dynamic performance views, which require SELECT_CATALOG_ROLE.
--
-- Until this is run, those four tools degrade gracefully and return a clear
-- "needs DBA grant" message instead of failing. After running it, they return
-- live data. This is read-only monitoring access — it grants no write ability.
--
-- Run as SYSTEM / a DBA against the PDB that holds MCP_APP (e.g. FREEPDB1):
--     sqlplus system@localhost:1521/FREEPDB1 @sql/grant_dba_monitor.sql
-- ============================================================================

-- Read-only access to the data dictionary and all V$ views.
GRANT SELECT_CATALOG_ROLE TO MCP_APP;

-- Optional: explicit individual grants instead of the role (uncomment if you
-- prefer least-privilege over the catch-all role above).
-- GRANT SELECT ON V_$SESSION        TO MCP_APP;
-- GRANT SELECT ON V_$SQL            TO MCP_APP;
-- GRANT SELECT ON V_$LOCK           TO MCP_APP;
-- GRANT SELECT ON V_$SYSTEM_EVENT   TO MCP_APP;
-- GRANT SELECT ON V_$SESSION_LONGOPS TO MCP_APP;
-- GRANT SELECT ON DBA_TABLESPACE_USAGE_METRICS TO MCP_APP;

-- SELECT_CATALOG_ROLE is not enabled by default inside PL/SQL definer-rights
-- code; for ad-hoc SELECTs from the app it is active immediately on reconnect.
COMMIT;

PROMPT Granted SELECT_CATALOG_ROLE to MCP_APP. Reconnect the app to pick it up.
