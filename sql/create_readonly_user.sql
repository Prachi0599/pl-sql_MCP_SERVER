-- ============================================================================
-- Dedicated READ-ONLY Oracle user for the MCP SQL read agent (sql_read_agent).
--
-- The SQL agent generates ad-hoc SELECTs from natural language. Running them as
-- this user gives a DB-ENFORCED guarantee that they can only read: the account
-- has CREATE SESSION + SELECT on MCP_APP tables and nothing else, so any
-- INSERT/UPDATE/DELETE/DDL fails at the database with ORA-01031 regardless of
-- what SQL is generated. (Statement validation in the agent remains as a second
-- layer of defense.)
--
-- HOW TO RUN — connect as a privileged user (SYSTEM or a DBA) to the SAME
-- pluggable database that holds MCP_APP (e.g. FREEPDB1), then run this whole
-- script. Examples:
--
--   sqlplus system@localhost:1521/FREEPDB1 @sql/create_readonly_user.sql
--   -- or paste it into DBeaver / SQL Developer connected as SYSTEM
--
-- BEFORE RUNNING: replace <CHOOSE_A_STRONG_PASSWORD> below with a real password,
-- then put the SAME values in your .env:
--   DB_READONLY_USER=MCP_RO
--   DB_READONLY_PASSWORD=<the password you set>
-- ============================================================================

-- 1. Create the user (drop first if re-running).
BEGIN
   EXECUTE IMMEDIATE 'DROP USER MCP_RO CASCADE';
EXCEPTION
   WHEN OTHERS THEN
      IF SQLCODE != -1918 THEN RAISE; END IF;  -- ORA-01918: user does not exist
END;
/

CREATE USER MCP_RO IDENTIFIED BY "<CHOOSE_A_STRONG_PASSWORD>";

-- 2. Let it connect. That is the ONLY system privilege it gets — no CREATE/
--    INSERT/UPDATE/DELETE anywhere.
GRANT CREATE SESSION TO MCP_RO;

-- 3. Grant SELECT on every current MCP_APP table (loops so new tables are easy
--    to re-grant by re-running this block).
BEGIN
   FOR t IN (SELECT table_name FROM all_tables WHERE owner = 'MCP_APP') LOOP
      EXECUTE IMMEDIATE 'GRANT SELECT ON MCP_APP.' || t.table_name || ' TO MCP_RO';
   END LOOP;
END;
/

-- 4. (Optional) confirm what MCP_RO can see.
--    SELECT COUNT(*) AS readable_mcp_app_tables
--    FROM all_tab_privs WHERE grantee = 'MCP_RO' AND privilege = 'SELECT';

-- The agent qualifies every table as MCP_APP.<TABLE> and reads ALL_TAB_COLUMNS /
-- ALL_CONSTRAINTS for schema discovery (both visible to MCP_RO via the grants
-- above), so no synonyms are required.
