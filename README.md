# TCL Finance & Billing — PL/SQL MCP Server

A **Model Context Protocol (MCP) server** that puts a natural-language, zero-SQL,
fully-audited, approval-gated interface in front of an Oracle Finance & Billing
schema. Ask questions in plain English ("how many active customers do we have?",
"investigate billing issues for CUST000122", "run the monthly billing for
2026-06") and the server classifies the request, routes it through a 3-layer
agent stack, calls the right Oracle packages/SQL, and returns structured JSON.

- **Language:** Python 3.11+ (async)
- **Database:** Oracle (`localhost:1521/FREEPDB1`, schema `MCP_APP`) via `oracledb`
- **LLM:** OpenAI **GPT-4o-mini** by default (agent routing + RCA/insight narratives).
  Override with the `OPENAI_MODEL` env var — every agent reads it.
- **Protocol:** MCP (`mcp` Python SDK / FastMCP), stdio transport
- **Tests:** `pytest` + `pytest-asyncio` — 300+ unit tests + live integration tests
  (`tests/test_task02.py` … `test_task25.py`)

### What's new in this revision
- **Model:** switched the default to `gpt-4o-mini` (cheaper/faster); all agents now
  honour `OPENAI_MODEL`.
- **DELETE support:** physical deletes are now first-class, approval-gated write
  tools (`delete_customer_note`, `delete_customer_address`, `delete_customer_contact`,
  `delete_costed_event`). Previously only INSERT/UPDATE worked.
- **Change reporting:** approving a write now reports **how many rows changed and
  what changed** (e.g. `1 row changed — account status: 'ACTIVE' -> 'INACTIVE'`).
- **DBA tools (Group N):** 12 diagnostics + 4 maintenance writes — database health,
  slow queries, deadlocks/blocking, wait events, tablespace usage, invalid objects,
  unused/redundant indexes, stale statistics, long operations; plus `drop_index`,
  `rebuild_index`, `gather_table_stats`, `recompile_object`. Exposed in plain English
  via the new `dba_agent`.
- **Conversation memory:** the chat client keeps context across turns — after an RCA
  you can say *"apply recommendation 2"* or *"what about his unpaid bills?"* and it
  stays on-thread.

### Follow-up fixes (round 2)
- **Hard deletes:** *"delete account ACC000123"* / *"delete customer CUST000122"* now
  do a real, FK-ordered cascade **delete** (after approval) — not a status change.
  `delete_account` / `delete_customer` remove the row and all dependents in one
  approved transaction.
- **Service requests** now always show **created-by, assigned-to, and the full
  description** (plus resolution notes and customer/account) — driven by an explicit
  query instead of the PL/SQL function's partial column set.
- **Onboarding executes:** *"onboard a new customer …"* stages the 5 steps and asks
  *"approve all? yes/no"* — a single **yes** applies all five (it no longer leaves
  everything PENDING forever).
- **"What did you change/create?"** is answered from this **session's** change log
  (exactly what you just did), instead of a DB-wide dump or a mis-routed schema list.
- **Account ops accept a customer number:** *"change account status for customer
  CUST000150"* resolves to that customer's account.
- **DBA V$ metrics** (slow queries, deadlocks/blocking, sessions, wait events) require
  Oracle's `SELECT_CATALOG_ROLE`. This is an Oracle privilege the `MCP_APP` app user
  lacks by default — **not** an app bug. Run `sql/grant_dba_monitor.sql` as a DBA once
  to enable live data; until then those four tools return a clear "needs DBA grant"
  message. All other DBA tools work without it.

---

## 1. What's in the box

| Layer | What it does | Code |
|---|---|---|
| **Atomic tools** (~80) | One Oracle call each — direct SQL or a PL/SQL package proc. Every call is audited. | `src/tools/*.py` |
| **ID resolvers** | Translate business codes (`CUST000122`, `USD`) → numeric IDs Oracle procs expect. | `src/db/resolvers.py` |
| **Sub-agents** (13) | Chain multiple tools for one job (e.g. RCA chains 7 tools + GPT-4o). | `src/agents/*_agent.py` |
| **SQL read agent** | Universal fallback — answers *any* read question by generating a safe, read-only `SELECT` (capped + audited). | `src/agents/sql_read_agent.py` |
| **Master agents** (2) | `read_master_agent` / `write_master_agent` — GPT-4o picks the right sub-agent. | `src/agents/*_master_agent.py` |
| **Intent router** (1) | Top entry point — classifies READ vs WRITE, routes to a master. | `src/agents/intent_router.py` |
| **MCP server** | Registers ~82 tools + 16 agents as MCP tools (incl. `ask` and `query_data`). | `src/server.py` |
| **Chat client** | Interactive REPL to talk to the stack yourself. | `chat.py` |

### Request flow

```
You: "Investigate billing issues for customer CUST000122"
  │
  ▼  intent_router            → classifies READ
  ▼  read_master_agent        → picks rca_agent
  ▼  rca_agent                → chains 7 read tools + GPT-4o synthesis
  ▼  atomic tools             → Oracle SQL / packages
  ▼  Oracle MCP_APP schema
  └─ returns { rca_summary, billing_issues, recommended_actions, ... }
```

Every WRITE is **never executed directly**. It is staged as a row in
`MCP_APPROVAL_REQUEST` (`status = PENDING`) and only runs the real DML after a
human calls `approve_request`. Every tool call is logged to `MCP_AUDIT_LOG`.

---

## 2. Prerequisites

1. **Python 3.11+**
2. **Oracle database** reachable at the DSN in your `.env`, with the `MCP_APP`
   schema loaded (20 tables, 19 sequences, 9 packages — Task 01).
3. **OpenAI API key** (the agents use GPT-4o for routing and narratives).

---

## 3. Setup

```bash
# from the project root: D:\Desktop\AI Projects\pl-sql_MCP_SERVER

# 1. create + activate a virtualenv
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell
# source .venv/bin/activate       # macOS/Linux

# 2. install dependencies
pip install -r requirements.txt

# 3. create your .env from the template and fill in real values
copy .env.example .env            # Windows
# cp .env.example .env            # macOS/Linux
```

Your `.env` must contain:

```
DB_USER=MCP_APP
DB_PASSWORD=mcp123
DB_CONNECT_STRING=localhost:1521/FREEPDB1
OPENAI_API_KEY=sk-...your-real-key...
OPENAI_MODEL=gpt-4o-mini
```

> `.env` is gitignored — your secrets never get committed. `.env.example` is the
> safe template (placeholder key only).

### Optional but recommended: a read-only DB user for the SQL agent

The universal `sql_read_agent` generates ad-hoc `SELECT`s. By default it runs
them as `DB_USER` and relies on statement validation (SELECT-only) to stay safe.
For a **database-enforced** guarantee, create a dedicated read-only account:

```bash
# run as SYSTEM / a DBA, against the PDB that holds MCP_APP (e.g. FREEPDB1):
sqlplus system@localhost:1521/FREEPDB1 @sql/create_readonly_user.sql
```

Edit `sql/create_readonly_user.sql` first to set a real password, then add the
matching values to `.env`:

```
DB_READONLY_USER=MCP_RO
DB_READONLY_PASSWORD=your-readonly-password-here
```

The agent then runs every generated query as `MCP_RO`, which only has
`CREATE SESSION` + `SELECT` on `MCP_APP` — so any INSERT/UPDATE/DELETE/DDL fails
at the database (ORA-01031). If these vars are unset, the agent transparently
falls back to the main pool (no behavior change).

### Optional: enable the full DBA performance metrics

The DBA tools (Group N) work out of the box for everything based on the data
dictionary (`USER_*`/`ALL_*` views): health, indexes, segments, statistics,
long operations. Four metrics — **active sessions, blocking/deadlocks, slow
queries, system wait events** — read the Oracle **V$** dynamic performance views,
which `MCP_APP` cannot see by default. Until granted, those four tools return a
clear *"needs DBA grant"* message (`available: false`) instead of failing.

To enable live data for them, run the grant script as a DBA:

```bash
sqlplus system@localhost:1521/FREEPDB1 @sql/grant_dba_monitor.sql
```

This grants `SELECT_CATALOG_ROLE` (read-only monitoring access — no write
ability). Reconnect the app afterwards.

---

## 4. Running it

### Option A — Web UI (browser, best experience)

A clean single-page chat UI in front of the same agent stack — plain-English
answers, RCA, DBA diagnostics, and **approval-gated writes with Approve / Cancel
buttons** (no typing `yes`/`no`), recommended-action chips after an RCA, and a
session/audit change recap. No extra dependencies (uses the bundled
`starlette` + `uvicorn`).

```bash
python web.py                      # then open http://127.0.0.1:8000
python web.py --port 9000          # custom port
python web.py --host 0.0.0.0       # expose on your LAN
```

Each browser tab is its own conversation. Writes are previewed and only applied
when you click **Approve**; onboarding stages all 5 steps and applies them on a
single Approve. Code: `web.py` (launcher), `src/web/app.py` (Starlette API),
`src/web/session.py` (per-session engine), `src/web/static/index.html` (UI).

### Option B — Interactive chat (terminal)

```bash
python chat.py
```

You'll get a REPL. Type plain English; you get plain-English answers back (no
JSON, no internal routing shown). `/help` for examples, `/quit` to exit.

```
you > how many active customers do we have?
  We currently have 142 active customers out of 200 total (58 are inactive).

you > set account ACC000123 status to ACTIVE
  Account ACC000123 status is already 'ACTIVE' - no change needed.

you > set account ACC000123 status to INACTIVE
  I've prepared this change (update account status). This will change it from
  'ACTIVE' to 'INACTIVE'. Reply 'yes' to approve and apply it, or 'no' to cancel.
you > yes
  Done - approved and applied (request #833).
```

**How writes behave (conversational approval):**
1. You ask for a change in plain English.
2. The system checks first and short-circuits if there's nothing to do — across
   **all** write types, not just updates:
   - status/flag/email update already at the target value -> "already X - no change needed"
   - create of a currency/provider that already exists -> "already exists - no change needed"
   - product already actively assigned, or already terminated -> "no change needed"
   - service request already assigned to that user / already resolved -> "no change needed"
   In every such case **nothing is staged**.
3. Otherwise you're shown exactly what will change (**from X to Y**, or what will
   be created) and asked to confirm. Reply **`yes`** to approve and apply, or
   **`no`** to cancel.

**Chat slash-commands** (optional shortcuts)

| Command | Effect |
|---|---|
| `/help` | Show example questions |
| `/raw` | Toggle full raw-JSON output (debugging) |
| `/pending` | List all PENDING approval requests |
| `/approve <id> <user>` | Approve a request directly — executes the staged DML |
| `/reject <id> <user>` | Reject a request directly — no DML runs |
| `/quit` `/exit` | Leave |

### Option C — Run as an MCP server (for Claude Desktop / any MCP client)

Both of these work (the second has a path bootstrap so running the file directly
no longer throws `ModuleNotFoundError: No module named 'src'`):

```bash
python -m src.server          # run as a module (canonical)
python src/server.py          # run the file directly (also works now)
```

The server speaks MCP over **stdio**, so it won't print a prompt — it waits for
an MCP client. To wire it into **Claude Desktop**, add this to
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tcl-finance-billing": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "D:\\Desktop\\AI Projects\\pl-sql_MCP_SERVER",
      "env": { "PYTHONPATH": "D:\\Desktop\\AI Projects\\pl-sql_MCP_SERVER" }
    }
  }
}
```

The client will then see ~99 tools, including the primary `ask` tool.

---

## 5. Testing

```bash
# everything that does NOT need the LLM (fast, ~3s) — 278 tests
python -m pytest tests/ -m "not integration" -q

# full suite incl. agent tests that call GPT-4o (~3 min) — 398 tests
python -m pytest tests/ -q

# one task's tests
python -m pytest tests/test_task24.py -v

# unit-only, no DB and no OpenAI needed at all
python -m pytest tests/ -m "not integration" -q
```

Integration tests auto-skip if `DB_USER` / `DB_CONNECT_STRING` are not set, so the
unit suite is safe to run anywhere.

**Manual validation:**
- [`docs/VALIDATION_QUESTIONS.md`](docs/VALIDATION_QUESTIONS.md) — a quick 25-question
  smoke script (reads, schema, RCA/insight, writes, no-op, approvals).
- [`docs/TEST_QUESTIONS.txt`](docs/TEST_QUESTIONS.txt) — the full bank: **165
  questions organized per tool and agent** (every atomic tool + every agent),
  with the real seed identifiers to use. Type them into `python chat.py`.
- [`docs/TEST_CASES_NEW_FEATURES.md`](docs/TEST_CASES_NEW_FEATURES.md) — focused,
  copy-paste validation for the five new features (gpt-4o-mini, DELETE, RCA
  follow-up, DBA tools, row-change reporting) with expected output for each.

---

## 6. Validation cookbook — commands + expected output

Use these to confirm the system is healthy. Run each and compare.

### 6.1 Server registers all tools

```bash
python -c "import asyncio, src.server as s; print(len(asyncio.run(s.mcp.list_tools())), 'tools')"
```
**Expected:** `125 tools`

### 6.2 Schema introspection (no LLM)

```bash
python -c "import asyncio; from src.tools.schema import list_packages; from src.db.pool import close_pool; r=asyncio.run(list_packages()); print(r['row_count'], 'packages'); [print(' ', p['package_name']) for p in r['data']]; asyncio.run(close_pool())"
```
**Expected:** `9 packages` — ACCOUNT_PKG, BILLING_ADJUSTMENT_PKG, BILLING_PKG,
CUSTOMER_PKG, LOAD_MONITOR_PKG, MCP_SECURITY_PKG, METADATA_PKG,
SERVICE_REQUEST_PKG, USAGE_ANALYTICS_PKG (all `VALID`).

### 6.3 Natural-language READ (full agent stack, uses GPT-4o)

In `python chat.py`:
```
you > List all PL/SQL packages in the schema
```
**Expected:** a plain-English reply naming the **9** packages (ACCOUNT_PKG,
BILLING_PKG, …) and noting they're all VALID. Use `/raw` to see the underlying JSON.

### 6.4 No-op / duplicate detection (write that changes nothing)

Applies to every write type. In `python chat.py` (ACC000123 is ACTIVE, USD exists):
```
you > set account ACC000123 status to ACTIVE
  Account ACC000123 status is already 'ACTIVE' - no change needed.

you > create a new currency USD called US Dollar
  Currency 'USD' already exists - no change needed.
```
**No approval request is created in either case.**

### 6.5 Natural-language WRITE → conversational approval

In `python chat.py`:
```
you > set account ACC000123 status to INACTIVE
```
**Expected:** a confirmation: *"This will change it from 'ACTIVE' to 'INACTIVE'.
Reply 'yes' to approve … or 'no' to cancel."* **Nothing is changed yet.**
```
you > yes
```
**Expected:** `Done - approved and applied (request #N).` Replying `no` instead
cancels it (the staged request is rejected, no DML runs).

### 6.6 Root-cause analysis (chains 7 tools + GPT-4o)

In `python chat.py`:
```
you > Investigate billing and usage issues for customer CUST000122
```
**Expected:** a plain-English root-cause summary for CUST000122 with any billing
issues and usage anomalies and recommended actions.

### 6.7 Ad-hoc data questions (universal SQL read agent)

The assistant can answer arbitrary data questions — not just the curated ones —
because `read_master_agent` falls back to `sql_read_agent`, which generates a
safe, read-only `SELECT`. In `python chat.py`:
```
you > show account details for ACC000123
you > show me all account numbers
you > what currency does account ACC000123 use
you > give me the top 5 customer ids
```
**Expected:** correct, data-backed answers for each (no "no records" for valid
data). Use `/raw` to see the generated SQL. Only `SELECT` is ever run; any
DML/DDL keyword or multi-statement input is rejected.

### 6.8 Change an account's currency (write + no-op)

In `python chat.py` (ACC000123 uses GBP in this example):
```
you > change account ACC000123 currency to GBP
  Account ACC000123 currency is already 'GBP' - no change needed.

you > change account ACC000123 currency to INR
  ...This will change it from 'GBP' to 'INR'. Reply 'yes' ... or 'no' ...
```

### 6.10 DBA / database-administration questions (Group N + dba_agent)

In `python chat.py`:
```
you > is the database healthy?
you > show me unused indexes I could remove
you > which tables have stale statistics?
you > are there any deadlocks or blocking sessions right now?
you > gather statistics for the CUSTOMER table
```
**Expected:** the first three return real data (health snapshot, ~17 review-candidate
indexes, the stale-stats tables). The deadlock/blocking question returns live data
only if `sql/grant_dba_monitor.sql` has been run; otherwise a clear *"needs DBA
grant"* note. The last stages a maintenance change for approval.

### 6.11 DELETE + change reporting

In `python chat.py`:
```
you > add a general note 'temp' for customer CUST000122 created by me
you > yes
  Done - approved and applied (request #N). — 1 row changed; insert note: created 1 row
you > delete customer note <that note id>
you > yes
  Done - approved and applied (request #N). — 1 row changed; delete customer note: deleted 1 row
```
**Expected:** every applied write now reports **rows changed** and a **before→after /
created / deleted** summary. Deleting a non-existent id replies *"… does not exist -
nothing to delete."* (no approval staged).

### 6.12 RCA recommendation follow-up (conversation memory)

In `python chat.py`:
```
you > investigate billing and usage issues for customer CUST000122
  <root-cause summary>
  Recommended actions (reply e.g. 'apply recommendation 1' or 'apply all'):
    1. ...
    2. ...
you > apply recommendation 1
  <stages the chosen action as a write for that same customer — context kept>
```
**Expected:** the assistant remembers the customer and the recommended actions, so
"apply recommendation 1" (or "apply all", "the second one") acts on them without you
re-stating the customer.

### 6.9 Real seed identifiers (for your own tests)

| Thing | Example value |
|---|---|
| Customer number | `CUST000122` |
| Invoicing company code | `INV0001` |
| Customer type code | `CORP`, `ENT`, `GOV`, `SMB`, `WHOLESALE` |
| Product code | `PROD0048` |
| Currency | `USD` |
| Account number | `ACC000123` |
| Invoice number | `INV00000123` |

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Ran a file in a way that didn't put the project root on `sys.path` | Run from the **project root** with `python -m src.server` or `python chat.py`. (`python src/server.py` now also works via a built-in path bootstrap.) |
| Integration tests all skipped | `DB_*` env vars not loaded | Ensure `.env` exists at project root with `DB_USER` and `DB_CONNECT_STRING`. |
| `OPENAI_*` / agent calls fail | Missing/invalid `OPENAI_API_KEY` | Put a real key in `.env`. Atomic-tool tests don't need it; agent tests do. |
| `ORA-12541` / `ORA-12514` | Oracle not reachable / wrong DSN | Check the DB is up and `DB_CONNECT_STRING` matches. |
| `RuntimeError: Event loop is closed` printed after a test run | Cosmetic Windows asyncio/httpx teardown warning from the OpenAI client | Harmless — tests still pass. |
| Unicode/`charmap` error in a custom script | Windows cp1252 console | The chat client already forces UTF-8; in your own scripts use ASCII or `sys.stdout.reconfigure(encoding="utf-8")`. |

---

## 8. Project layout

```
pl-sql_MCP_SERVER/
├── chat.py                 # interactive REPL client  (python chat.py)
├── README.md               # this file
├── requirements.txt
├── .env.example            # template (no real secrets)
├── pytest.ini
├── docs/
│   └── PRD.md              # full product/design spec, schema, tool catalogue
├── src/
│   ├── server.py           # MCP entry point — registers 80 tools + 15 agents
│   ├── db/
│   │   ├── pool.py         # async oracledb connection pool (min=2, max=10)
│   │   └── resolvers.py    # business code -> numeric ID resolvers
│   ├── tools/              # ~80 atomic tools, grouped by domain
│   │   ├── schema.py  account.py  reference.py  customer.py
│   │   ├── billing.py usage.py    power.py      approval.py  writes.py
│   ├── agents/             # 16 agents (router, masters, sub-agents,
│   │                       #   incl. sql_read_agent = universal text-to-SQL)
│   └── utils/
│       ├── audit.py        # MCP_SECURITY_PKG.LOG_AUDIT wrapper
│       └── errors.py       # ORA-xxxxx -> human-readable message mapper
└── tests/                  # test_task02 .. test_task24 (+ conftest)
```

See [`docs/PRD.md`](docs/PRD.md) for the full schema, the 80-tool catalogue, the
12-agent catalogue, and the approval/audit framework design.
