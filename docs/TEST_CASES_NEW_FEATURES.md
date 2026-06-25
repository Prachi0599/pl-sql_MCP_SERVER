# Test Cases — New Features

Validation script for the five changes in this revision. Run each block and
compare against **Expected**. Three ways to test:

- **A. Automated** — `pytest` (fastest, no typing).
- **B. Chat** — `python chat.py`, type the lines, read the replies.
- **C. Python one-liner** — for the tool layer directly.

Seed identifiers used below: customer `CUST000122`, account `ACC000123`,
invoice `INV00000123`.

---

## 0. Run the automated suite first

```bash
# Unit tests only (no DB, no OpenAI) — should be all green
python -m pytest tests/ -m "not integration" -q

# The new-feature tests specifically
python -m pytest tests/test_task25.py -q                 # unit + integration
python -m pytest tests/test_task25.py -m integration -q  # live DB only
```

**Expected:** unit suite `300+ passed`; `tests/test_task25.py` all pass
(integration auto-skips if `DB_*` env vars are unset).

---

## Task 1 — Use `gpt-4o-mini` instead of `gpt-4o`

**C. Python**
```bash
python -c "from src.agents import intent_router as r; print(r._MODEL)"
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('env=',os.getenv('OPENAI_MODEL'))"
```
**Expected:** `gpt-4o-mini` for both. (Override anytime by setting
`OPENAI_MODEL` in `.env` — every agent honours it.)

**Automated:** `pytest tests/test_task25.py -k "t25_01 or t25_02 or t25_03" -q`
— confirms no hardcoded `gpt-4o` literal remains and the env override works.

---

## Task 2 — DELETE operations (previously broken)

**B. Chat**
```
you > delete customer note 999999
  Customer note 999999 does not exist - nothing to delete.

you > add a general note 'temp delete test' for customer CUST000122 created by qa
you > yes
  Done - approved and applied (request #N). — 1 row changed; insert note: created 1 row
# note its NOTE_ID from /raw or the audit log, then:
you > delete customer note <NOTE_ID>
  I've prepared this change ... Reply 'yes' ...
you > yes
  Done - approved and applied (request #N). — 1 row changed; delete customer note: deleted 1 row
```
**Expected:** the request is classified **WRITE → dml_agent → delete_customer_note**
(use `/raw` to see the route). A real delete reports `1 row changed`; a missing id
is a friendly no-op with nothing staged.

Other supported deletes: `delete customer address <id>`, `delete customer contact
<id>` (also removes its phone/contact-details child), `delete costed event <id>`.

**Automated:** `pytest tests/test_task25.py -k "t25_04 or t25_05 or t25_07 or t25_33" -q`

---

## Task 3 — RCA recommendation keeps context

**B. Chat**
```
you > investigate billing and usage issues for customer CUST000122
  <root-cause summary in plain English>
  Recommended actions (reply e.g. 'apply recommendation 1' or 'apply all'):
    1. <action one>
    2. <action two>

you > apply recommendation 1
  <stages action 1 as a write FOR CUST000122 — you are NOT asked who/which customer>

you > what about his unpaid bills?
  <answers for CUST000122 — the customer is remembered>
```
**Expected:** after the RCA, "apply recommendation 1" / "apply all" / "the second
one" act on the listed actions for the **same customer** without you re-stating it;
pronoun follow-ups ("his/their …") stay scoped to that customer.

**Automated:** `pytest tests/test_task25.py -k "t25_18 or t25_19 or t25_20" -q`
— covers ordinal parsing ("the second one" → 2), "apply all", and pronoun scoping.

---

## Task 4 — DBA tools (all DBA operations)

**B. Chat** (natural language → `dba_agent`)
```
you > is the database healthy?
you > show me unused indexes I could remove
you > which tables have stale statistics?
you > what are the largest segments in the schema?
you > are there invalid objects?
you > are there deadlocks or blocking sessions?      # needs DBA grant (see below)
you > what are the slowest queries?                  # needs DBA grant
you > gather statistics for the CUSTOMER table        # maintenance write -> approval
you > rebuild index <INDEX_NAME>                      # maintenance write -> approval
```

**C. Python** (tool layer, read-only)
```bash
python -c "import asyncio; from src.tools.dba import get_database_health as f; from src.db.pool import close_pool; r=asyncio.run(f()); print(r['data']['status'], r['data']['object_counts']); asyncio.run(close_pool())"
python -c "import asyncio; from src.tools.dba import get_unused_indexes as f; from src.db.pool import close_pool; r=asyncio.run(f()); print(r['row_count'],'review-candidate indexes'); asyncio.run(close_pool())"
```

**Expected:**
- Dictionary-based tools return real data: health `HEALTHY` with object counts,
  ~17 unused-index candidates, stale-stats tables, segment sizes, invalid objects (0).
- The **V$-based** tools (active sessions, blocking/deadlocks, slow queries, wait
  events) return `success: true, available: false` with a *"needs DBA grant"*
  message **until** you run `sql/grant_dba_monitor.sql` as a DBA, after which they
  return live data.
- Maintenance verbs (gather stats / drop index / rebuild index / recompile) are
  **staged for approval** — nothing runs until you reply `yes`.

Full DBA tool list (16): `get_database_health`, `get_active_sessions`,
`get_blocking_sessions`, `get_slow_queries`, `get_wait_events`,
`get_tablespace_usage`, `get_segment_sizes`, `get_invalid_objects`,
`get_unused_indexes`, `get_redundant_indexes`, `get_table_stats_status`,
`get_long_operations`, `drop_index`, `rebuild_index`, `gather_table_stats`,
`recompile_object`.

**Automated:** `pytest tests/test_task25.py -k "t25_12 or t25_13 or t25_14 or t25_15 or t25_16 or t25_30 or t25_31 or t25_32" -q`

---

## Task 5 — Show rows changed + what changed after a DML

**B. Chat**
```
you > set account ACC000123 status to INACTIVE
  I've prepared this change (update account status). This will change it from
  'ACTIVE' to 'INACTIVE'. Reply 'yes' ...
you > yes
  Done - approved and applied (request #N). — 1 row changed; update account status: 'ACTIVE' -> 'INACTIVE'
```
**Expected:** after every applied write the reply states **how many rows changed**
and a **summary of the change** (before→after for updates, "created N" for inserts,
"deleted N" for deletes). The same data is available on the tool result as
`rows_affected` and `change_summary`.

**C. Python** (verify the fields exist on an approval result)
```bash
python -c "from src.tools.approval import _describe_change as d; import json; print(d('UPDATE', json.dumps({'old_status':'ACTIVE'}), json.dumps({'params':[1,'INACTIVE']}), 'UPDATE_ACCOUNT_STATUS', 1))"
```
**Expected:** `update account status: 'ACTIVE' -> 'INACTIVE' (1 row changed)`

**Automated:** `pytest tests/test_task25.py -k "t25_09 or t25_10 or t25_11" -q`

---

---

# Round-2 fixes (follow-up issues)

Run `pytest tests/test_task25.py -q` to cover all of these automatically
(unit `t25_21`–`t25_29`, live `t25_34`–`t25_36`). Manual steps below.

## R1. DBA V$ metrics ("slowest queries", "deadlocks") show no records
This is **not a bug** — Oracle's V$ performance views require `SELECT_CATALOG_ROLE`,
which the application user `MCP_APP` does not have by default. The tools work the
moment a DBA grants it:
```bash
sqlplus system@localhost:1521/FREEPDB1 @sql/grant_dba_monitor.sql
```
Then in chat: `what are the slowest queries?` / `are there deadlocks?` return live
data. (All other DBA tools — health, indexes, stats, segments — work without it.)
**Expected before grant:** a clear "needs DBA grant" message, `available:false`.
**Expected after grant:** live rows.

## R2. "delete" must really delete (no silent status change)
```
you > delete account ACC000XXX        # use a throwaway account
  I've prepared this change (delete account) ... Reply 'yes' ...
you > yes
  Done - approved and applied (request #N). — delete account: deleted N rows
```
**Expected:** routed to `delete_account` (a hard delete of the account + its bills,
events, adjustments, product links), **not** `update_account_status`. Same for
`delete customer CUST000XXX` → `delete_customer` (removes the customer and ALL
related accounts, contacts, addresses, notes, tickets). Irreversible after approval.
> Tip: create a throwaway first (`create a customer …` / onboarding) so you don't
> delete seed data. Automated test `t25_36` does exactly this round-trip.

## R3. Service requests show created-by / assigned-to / description
```
you > show open service requests
```
**Expected:** each request lists **Description, Raised/Created By, Assigned To**
(shows "Unassigned" when empty), Resolution Notes, Customer, Account, and dates —
not just id/type/priority/status.

## R4. Onboarding actually creates (not stuck PENDING)
```
you > Onboard a new customer 'Globex Ltd', company INV0001, type CORP, billing
      address '5 Market St, Delhi, IN', contact 'Sam Lee' Director sam@globex.com,
      account 'Globex Main' in USD, product PROD0048.
  I've prepared a 5-step onboarding for CUST-0xxxxx (account ACC-0xxxxx):
    1..5 ...
  Reply 'yes' to approve and apply ALL steps, or 'no' to cancel.
you > yes
  Done - onboarding for CUST-0xxxxx: applied 5 of 5 steps.
```
**Expected:** a single **yes** applies all five steps. (Previously they stayed
PENDING.)

## R5. "What did you change/create?" = this session only
After making a change in the same chat session:
```
you > show me what you have changed
  Here's what I've changed in this session (most recent first):
    1. account status: 'ACTIVE' -> 'INACTIVE' (request #N)
```
**Expected:** only the changes **you** made in this session, newest first — not a
DB-wide pending dump and not a schema/table listing. Phrasings like *"what changes
has made"*, *"show me what you inserted"*, *"show me the changes"* all work.

**Cross-session fallback:** if you've just started a fresh `chat.py` (empty session
log), the same question instead lists the **most recently approved changes from the
approval history** (with who approved them and when) — so you still see what was
applied in earlier sessions. Tool: `get_recent_changes`.

## R6. Account ops accept a customer number
```
you > change account status to ACTIVE for customer CUST000150
```
**Expected:** resolves to that customer's account (`ACC000150`) and stages the
change, instead of "Account not found". (If the customer has several accounts, it
asks which one.)

---

## One-shot regression check

```bash
python -m pytest tests/ -m "not integration" -q          # all unit tests
python -c "import asyncio, src.server as s; print(len(asyncio.run(s.mcp.list_tools())), 'tools')"
```
**Expected:** unit suite all green; `125 tools` registered.
