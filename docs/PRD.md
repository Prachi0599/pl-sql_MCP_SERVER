# Product Requirements Document
# TCL Finance & Billing — Enterprise PL/SQL MCP Server
**Version:** 4.0 (Updated — Task 01 Complete)
**Company:** TCL (Telecom / Service Provider)
**Project:** Finance & Billing Platform
**Database:** Oracle FREEPDB1 / Schema: MCP_APP
**Stack:** Node.js + TypeScript | node-oracledb | MCP SDK | Anthropic API
**MCP Client:** Claude Desktop (`claude_desktop_config.json`)
**Last Updated:** June 2026

---

## Build Progress Tracker

| Task | Description | Status |
|---|---|---|
| TASK 01 | Oracle Schema — new tables, sequences, packages | ✅ COMPLETE |
| TASK 02 | Node.js Project Scaffold & Oracle Connection | 🔲 Next |
| TASK 03 | ID Resolver Helpers | 🔲 Pending |
| TASK 04 | Schema Introspection Tools (Group L) | 🔲 Pending |
| TASK 05 | Reference & Lookup Read Tools | 🔲 Pending |
| TASK 06 | Customer Read Tools | 🔲 Pending |
| TASK 07 | Address, Contact, Account Read Tools | 🔲 Pending |
| TASK 08 | Product & Billing Read Tools | 🔲 Pending |
| TASK 09 | Usage Analytics & Operations Read Tools | 🔲 Pending |
| TASK 10 | Cross-Entity Power Query Tools | 🔲 Pending |
| TASK 11 | Approval Workflow Engine | 🔲 Pending |
| TASK 12 | All Write Tools | 🔲 Pending |
| TASK 13 | Error Handling, Pagination & Security | 🔲 Pending |
| TASK 14 | schema_agent | 🔲 Pending |
| TASK 15 | customer_read_agent + billing_read_agent | ✅ COMPLETE |
| TASK 16 | usage_read_agent + operations_read_agent | ✅ COMPLETE |
| TASK 17 | rca_agent | ✅ COMPLETE |
| TASK 18 | insight_agent | ✅ COMPLETE |
| TASK 19 | READ MASTER AGENT | ✅ COMPLETE |
| TASK 20 | dml_agent + approval_agent | ✅ COMPLETE |
| TASK 21 | onboarding_agent | ✅ COMPLETE |
| TASK 22 | billing_run_agent + adjustment_agent | ✅ COMPLETE |
| TASK 23 | WRITE MASTER AGENT + INTENT ROUTER | ✅ COMPLETE |
| TASK 24 | End-to-End Integration Test | 🔲 Pending |

---

## Table of Contents

1. [Project Background](#1-project-background)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [User Personas](#4-user-personas)
5. [Schema Overview — FINAL](#5-schema-overview--final)
6. [Overall Architecture](#6-overall-architecture)
7. [Agent Architecture — 3-Layer Design](#7-agent-architecture--3-layer-design)
8. [Package Inventory — FINAL](#8-package-inventory--final)
9. [Tool Catalogue — 80 Tools](#9-tool-catalogue--80-tools)
10. [Agent Catalogue — 12 Sub-Agents](#10-agent-catalogue--12-sub-agents)
11. [Approval & Audit Framework](#11-approval--audit-framework)
12. [ID Resolution Layer](#12-id-resolution-layer)
13. [Non-Functional Requirements](#13-non-functional-requirements)
14. [Known Gaps & Fixes](#14-known-gaps--fixes)
15. [DBeaver Tips — Lessons Learned](#15-dbeaver-tips--lessons-learned)
16. [Out of Scope v1](#16-out-of-scope-v1)
17. [Implementation Tasks with Unit Tests](#17-implementation-tasks-with-unit-tests)

---

## 1. Project Background

TCL is a service provider delivering domestic and international services to enterprise clients.
The Finance & Billing team owns the full lifecycle of customer financial data:

- **Onboarding** — capturing customer, account, contact, address, and product details
- **Daily Operations** — receiving usage/event data from source systems, resolving data issues, performing DML corrections
- **Billing** — generating invoices based on service usage, billing cycles, and currency
- **Reporting** — dashboards, revenue reports, usage analytics for stakeholders
- **Support** — root cause analysis (RCA) for billing discrepancies, data issues, and complaints

Every one of these activities currently requires a team member to manually write SQL,
navigate a complex schema, and execute scripts in DBeaver. This is slow, error-prone,
and creates a high knowledge barrier for new joiners.

---

## 2. Problem Statement

| Pain Point | Who Feels It | Current Workaround |
|---|---|---|
| Must write SQL for every data request | All team members | Copy-paste from old scripts |
| New joiners spend weeks learning schema | Developers, Engineers | Senior developer hand-holding |
| Finding which procedure handles an issue takes hours | Support Engineers | Manual grep through package bodies |
| Business stakeholders cannot self-serve data | Managers, Analysts | Raise a ticket to dev team |
| No audit trail for ad-hoc DML operations | Team Leads, Compliance | Manual log in Excel |
| RCA investigations require multiple complex JOINs | Support Engineers | Senior dev writes query on demand |
| Risk of accidental DML on production finance data | Everyone | Hope and peer review |
| No visibility into daily data load status | Operations | Manual row count queries each morning |

---

## 3. Goals & Success Metrics

### Primary Goals
- Zero-SQL data access for business stakeholders and analysts
- RCA investigation time reduced from hours to minutes
- New joiners productive on day one without schema documentation
- Safe, audited, approval-gated channel for all DML operations
- Automated invoice generation workflow replacing manual steps
- Daily operational health checks available in one command

### Success Metrics (3 months post-launch)

| Metric | Target |
|---|---|
| Time to answer a billing query (stakeholder) | < 30 seconds (was: hours) |
| Time for new joiner to find relevant procedure | < 1 minute (was: days) |
| RCA resolution time for support engineers | < 10 minutes (was: 2–4 hours) |
| Ad-hoc DML with full audit trail | 100% |
| Reduction in dev team query requests | > 70% |

---

## 4. User Personas

### Persona 1 — Developer / Database Engineer
**Goal:** Debug issues, understand schema, seed test data, find procedures fast

- "What does BILLING_PKG.GENERATE_BILL do and what parameters does it take?"
- "Show me all procedures that touch the BILL_SUMMARY table"
- "Which accounts have events but no bill this month?"

### Persona 2 — Support Engineer
**Goal:** Quickly find root cause of customer complaints, fix data issues safely

- "Customer CUST-1042 says their invoice is wrong — investigate and give me the RCA"
- "Account ACC-8821 has been active 3 months but has no costed events — why?"
- "Show me all FAILED events from source system MEDIATION today"

### Persona 3 — Business Analyst
**Goal:** Generate reports, revenue trends, product adoption data without SQL

- "What is our total revenue for June 2026 broken down by currency?"
- "Which product type generated the most revenue last quarter?"
- "Show me the top 10 accounts by data usage this month"

### Persona 4 — Business Stakeholder / Manager
**Goal:** Self-serve answers without raising tickets to the dev team

- "How many active customers do we have under invoicing company EMEA-01?"
- "What is the total outstanding invoice amount in USD?"
- "Give me an executive revenue summary for Q1 2026"

### Persona 5 — New Joiner
**Goal:** Understand the schema and codebase on day one

- "What tables exist in this schema and what does each store?"
- "What is the relationship between CUSTOMER and ACCOUNT?"
- "What procedure should I use to create a new customer?"

---

## 5. Schema Overview — FINAL

### ✅ Verified Database State (as of Task 01 completion)

| Object Type | Count | Status |
|---|---|---|
| Tables | 20 | ✅ All created and verified |
| Sequences | 19 | ✅ All created and verified |
| Packages | 9 | ✅ All VALID |
| Package Bodies | 9 | ✅ All VALID |
| Indexes | 50 | ✅ Auto-created with constraints |

### Entity Relationship

```
PROVIDER
  └── INVOICING_COMPANY
        └── CUSTOMER ──── CUSTOMER_TYPE
              ├── ADDRESS
              ├── CONTACT ──── CONTACT_DETAILS
              ├── CUSTOMER_NOTE               ✅ NEW — RCA notes
              └── ACCOUNT ──── CURRENCY
                    ├── ACCOUNT_DETAILS
                    ├── BILL_SUMMARY
                    │     └── BILLING_ADJUSTMENT   ✅ NEW — credits/waivers
                    ├── COSTED_EVENT
                    └── CUSTOMER_PRODUCT_DETAILS ── PRODUCT

[Operations]
  └── DAILY_LOAD_LOG                          ✅ NEW — source system monitoring

[Support]
  └── SERVICE_REQUEST                         ✅ NEW — RCA ticket tracking

[MCP Infrastructure]
  ├── MCP_AUDIT_LOG
  └── MCP_APPROVAL_REQUEST
```

### Complete Table Reference (20 tables)

| Table | Purpose | Key Columns |
|---|---|---|
| `PROVIDER` | TCL or partner service providers | PROVIDER_CODE, SERVICE_TYPE, STATUS |
| `INVOICING_COMPANY` | Legal entity that invoices customers | COMPANY_CODE, COUNTRY, STATUS |
| `CUSTOMER` | Enterprise clients of TCL | CUSTOMER_NUMBER, CUSTOMER_NAME, STATUS |
| `CUSTOMER_TYPE` | Lookup: Enterprise, SMB, Government | CUSTOMER_TYPE_CODE, CUSTOMER_TYPE_NAME |
| `ADDRESS` | Customer billing/service addresses | ADDRESS_TYPE, CITY, COUNTRY |
| `CONTACT` | Key contacts at customer org | CONTACT_NAME, DESIGNATION, EMAIL |
| `CONTACT_DETAILS` | Phone and alternate email | PHONE_NUMBER, ALTERNATE_EMAIL |
| `ACCOUNT` | Billing account per customer | ACCOUNT_NUMBER, BILLING_CYCLE, STATUS |
| `ACCOUNT_DETAILS` | Commissioning/termination metadata | BILLABLE_FLAG, COMMISSIONING_DATE, TERMINATION_DATE |
| `CURRENCY` | Supported billing currencies | CURRENCY_CODE, CURRENCY_NAME |
| `PRODUCT` | Services TCL provides | PRODUCT_CODE, PRODUCT_TYPE, STATUS |
| `CUSTOMER_PRODUCT_DETAILS` | Product subscriptions | START_DATE, END_DATE, STATUS |
| `BILL_SUMMARY` | Generated invoices | INVOICE_NUMBER, BILL_AMOUNT, TOTAL_AMOUNT, BILL_STATUS |
| `COSTED_EVENT` | Daily usage/network events | EVENT_DTM, IN_BITS, OUT_BITS, SPEED_MBPS, SOURCE_SYSTEM |
| `MCP_AUDIT_LOG` | Every MCP tool call logged | TOOL_NAME, ACTION_TYPE, STATUS, ERROR_MESSAGE |
| `MCP_APPROVAL_REQUEST` | DML approval queue | OLD_VALUE, NEW_VALUE, STATUS, APPROVED_BY |
| `DAILY_LOAD_LOG` ✅ NEW | Daily source system load tracking | SOURCE_SYSTEM, RECORDS_RECEIVED, RECORDS_LOADED, STATUS |
| `SERVICE_REQUEST` ✅ NEW | RCA tickets and data fix requests | REQUEST_TYPE, PRIORITY, STATUS, RAISED_BY, ASSIGNED_TO |
| `BILLING_ADJUSTMENT` ✅ NEW | Credits, debits, waivers on invoices | ADJUSTMENT_TYPE, ADJUSTMENT_AMOUNT, STATUS |
| `CUSTOMER_NOTE` ✅ NEW | Free-text RCA notes on customers | NOTE_TYPE, NOTE_TEXT, CREATED_BY |

### Complete Sequence Reference (19 sequences)

| Sequence | Table |
|---|---|
| SEQ_PROVIDER | PROVIDER |
| SEQ_INV_COMPANY | INVOICING_COMPANY |
| SEQ_CUSTOMER | CUSTOMER |
| SEQ_CUSTOMER_TYPE | CUSTOMER_TYPE |
| SEQ_ADDRESS | ADDRESS |
| SEQ_CONTACT | CONTACT |
| SEQ_CONTACT_DETAILS | CONTACT_DETAILS |
| SEQ_ACCOUNT | ACCOUNT |
| SEQ_BILL_SUMMARY | BILL_SUMMARY |
| SEQ_COSTED_EVENT | COSTED_EVENT |
| SEQ_CURRENCY | CURRENCY |
| SEQ_PRODUCT | PRODUCT |
| SEQ_CUST_PRODUCT | CUSTOMER_PRODUCT_DETAILS |
| SEQ_MCP_AUDIT_LOG | MCP_AUDIT_LOG |
| SEQ_MCP_APPROVAL_REQUEST | MCP_APPROVAL_REQUEST |
| SEQ_DAILY_LOAD_LOG ✅ NEW | DAILY_LOAD_LOG |
| SEQ_SERVICE_REQUEST ✅ NEW | SERVICE_REQUEST |
| SEQ_BILLING_ADJUSTMENT ✅ NEW | BILLING_ADJUSTMENT |
| SEQ_CUSTOMER_NOTE ✅ NEW | CUSTOMER_NOTE |

---

## 6. Overall Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Claude Desktop (MCP Client)                     │
│          User types natural language — gets structured answer    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ JSON-RPC over stdio
┌───────────────────────────▼─────────────────────────────────────┐
│              TCL Finance & Billing MCP Server                    │
│                    (Node.js / TypeScript)                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  LAYER 1: INTENT ROUTER                   │   │
│  │     Classifies every request as READ or WRITE             │   │
│  │     Routes to correct Master Agent                        │   │
│  └────────────────────┬─────────────────┬────────────────────┘  │
│                       │                 │                        │
│  ┌────────────────────▼──┐   ┌──────────▼─────────────────┐    │
│  │  LAYER 2: READ MASTER  │   │  LAYER 2: WRITE MASTER      │   │
│  │  All retrieval ops     │   │  All DML + approval          │   │
│  └──────────┬────────────┘   └──────────┬──────────────────┘   │
│             │                            │                       │
│  ┌──────────▼──────────────────────────────────────────────┐    │
│  │            LAYER 3: SUB-AGENTS (12 total)                │   │
│  │  READ:  customer | billing | usage | ops | rca           │   │
│  │         schema | insight (Claude API)                    │   │
│  │  WRITE: dml | approval | onboarding | billing_run | adj  │   │
│  └──────────┬──────────────────────────────────────────────┘   │
│             │                                                    │
│  ┌──────────▼──────────────────────────────────────────────┐   │
│  │     ATOMIC TOOLS (80 tools) + ID RESOLVERS               │   │
│  │     Zod Validation | Audit Logger | Error Mapper          │   │
│  └──────────┬──────────────────────────────────────────────┘   │
└─────────────┼────────────────────────────────────────────────────┘
              │ node-oracledb connection pool
┌─────────────▼────────────────────────────────────────────────────┐
│     Oracle FREEPDB1 / MCP_APP — 20 Tables | 9 Packages           │
│     19 Sequences | 50 Indexes — ALL ✅ VERIFIED                   │
└──────────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Component | Choice |
|---|---|
| Runtime | Node.js 20 LTS + TypeScript |
| MCP SDK | @modelcontextprotocol/sdk |
| Oracle Driver | node-oracledb (connection pool min=2 max=10) |
| Input Validation | zod |
| LLM Calls (agents) | Anthropic API — claude-sonnet-4-6 |
| Config | dotenv |
| Testing | jest + ts-jest |
| Logging | winston + MCP_AUDIT_LOG |

---

## 7. Agent Architecture — 3-Layer Design

### Layer 1 — Intent Router

Single entry point. Classifies any natural language input as READ or WRITE,
identifies the domain, and routes to the correct master agent.

```
"What is the outstanding amount for CUST-1042?"
  → READ → billing_read_agent → get_billing_summary_by_customer

"Create account ACC-9001 for Acme Corp"
  → WRITE → dml_agent → create_account → Approval workflow

"Investigate why customer CUST-1042 has a wrong bill"
  → READ → rca_agent → chains 7 tools + Claude API

"Generate all monthly invoices for June 2026"
  → WRITE → billing_run_agent → batch create_bill approvals
```

### Layer 2 — Master Agents

**READ MASTER AGENT**
- Scope: All SELECT / retrieval / analytics / investigation
- Rules: NEVER executes INSERT/UPDATE/DELETE
- Logs every call with ACTION_TYPE='READ'

**WRITE MASTER AGENT**
- Scope: All INSERT / UPDATE / DELETE
- Rules: ALWAYS creates MCP_APPROVAL_REQUEST first
- NEVER executes DML without STATUS='APPROVED'
- Returns { request_id, status: 'PENDING' } — not data

### Layer 3 — Sub-Agents (13 total)

> **sql_read_agent (universal read fallback).** In addition to the curated read
> agents below, `read_master_agent` can route to `sql_read_agent`, which answers
> arbitrary data questions by having GPT-4o generate a single read-only Oracle
> SELECT against the live MCP_APP schema, validating it (SELECT-only, no DML/DDL,
> no statement chaining), executing it with a hard row cap, and auditing it. This
> guarantees broad coverage: specific record/field lookups, lists, ids, counts,
> and ad-hoc filters that no dedicated tool exists for. Also exposed directly as
> the MCP tool `query_data`.

#### Under READ MASTER (8)

**1. customer_read_agent**
Handles customer lookups, contacts, addresses, products, health checks.
Tools: search_customers, get_customer_360, get_customer_addresses,
get_customer_contacts, get_customer_products, get_customer_health_check,
get_customer_summary_stats, get_expiring_products

**2. billing_read_agent**
Handles invoice lookups, revenue reports, payment status.
Tools: get_bills_by_account, get_bill_by_invoice_number,
get_billing_summary_by_customer, get_unpaid_bills,
get_monthly_revenue, get_revenue_by_product_type, get_pending_adjustments

**3. usage_read_agent**
Handles costed events, bandwidth analytics, anomaly detection.
Tools: get_events_by_account, get_event_summary, get_top_usage_accounts,
get_events_by_source_system, get_bandwidth_trend,
get_failed_events, get_usage_anomalies

**4. operations_read_agent**
Handles daily load monitoring, data quality, service requests.
Tools: get_load_status_today, get_missing_loads, get_load_history,
get_failed_load_summary, get_open_requests, get_requests_by_customer,
get_inactive_entities, get_accounts_pending_termination

**5. rca_agent** ← Most powerful read agent
Chains 7 tools + calls Claude API. Full automated investigation.
Flow: customer_360 → bills → events → failed_events →
load_status → health_check → anomalies → Claude API → RCA report

**6. schema_agent** ← New joiner's best friend
Handles schema introspection, package discovery, procedure lookup.
Tools: list_tables, describe_table, list_packages,
list_package_procedures, get_procedure_signature,
list_sequences, list_indexes, find_procedure_for_table

**7. insight_agent** ← Claude API powered reports
Executive summaries and narrative reports for business stakeholders.
Flow: revenue + product breakdown + top accounts +
unpaid bills + load summary → Claude API → English narrative

#### Under WRITE MASTER (5)

**8. dml_agent**
Any single INSERT/UPDATE/DELETE via approval workflow.
Always: validate → resolve codes → create approval → return request_id

**9. approval_agent**
Manages the approval queue.
Tools: get_pending_approvals, approve_request, reject_request,
get_my_pending_requests

**10. onboarding_agent**
Full customer onboarding in one command — creates 5 approval
requests in correct dependency order:
customer → address → contact → account → product assignment

**11. billing_run_agent**
Batch invoice generation. Checks billable flag, event existence,
anomalies — queues approve requests for all eligible accounts.

**12. adjustment_agent**
Billing credits, debits, waivers, disputes via approval workflow.

---

## 8. Package Inventory — FINAL

### ✅ All 9 Packages Verified VALID

| Package | Type | Procedures / Functions | Status |
|---|---|---|---|
| `CUSTOMER_PKG` | Business | CREATE_CUSTOMER, UPDATE_CUSTOMER_STATUS, GET_CUSTOMER_DETAILS | ✅ VALID |
| `ACCOUNT_PKG` | Business | CREATE_ACCOUNT, UPDATE_ACCOUNT_STATUS, GET_ACCOUNT_DETAILS | ✅ VALID |
| `BILLING_PKG` | Business | GENERATE_BILL, UPDATE_BILL_STATUS, GET_BILL_DETAILS | ✅ VALID |
| `USAGE_ANALYTICS_PKG` | Analytics | GET_ACCOUNT_USAGE, GET_TOP_BANDWIDTH_ACCOUNTS, GET_USAGE_ANOMALIES | ✅ VALID |
| `MCP_SECURITY_PKG` | Infrastructure | LOG_AUDIT, CREATE_APPROVAL_REQUEST, APPROVE_REQUEST, REJECT_REQUEST | ✅ VALID — G5/G6 fixed |
| `METADATA_PKG` | Introspection | LIST_PACKAGES, LIST_PACKAGE_PROCEDURES, GET_PACKAGE_ARGUMENTS | ✅ VALID |
| `LOAD_MONITOR_PKG` | Operations | LOG_LOAD_START, LOG_LOAD_END, GET_LOAD_STATUS, GET_MISSING_LOADS, GET_LOAD_HISTORY, GET_FAILED_LOAD_SUMMARY | ✅ VALID NEW |
| `SERVICE_REQUEST_PKG` | Support | CREATE_REQUEST, ASSIGN_REQUEST, RESOLVE_REQUEST, CLOSE_REQUEST, GET_OPEN_REQUESTS, GET_REQUESTS_BY_CUSTOMER, GET_REQUESTS_BY_TYPE | ✅ VALID NEW |
| `BILLING_ADJUSTMENT_PKG` | Finance | CREATE_ADJUSTMENT, APPROVE_ADJUSTMENT, REJECT_ADJUSTMENT, APPLY_ADJUSTMENT, GET_PENDING_ADJUSTMENTS, GET_ADJUSTMENTS_BY_BILL, GET_ADJUSTMENTS_BY_ACCOUNT | ✅ VALID NEW |

### Key Package Notes

**MCP_SECURITY_PKG — Gaps G5 & G6 Fixed ✅**
APPROVE_REQUEST uses `PRAGMA EXCEPTION_INIT(E_ROW_LOCKED, -54)` for row locking.
REJECT_REQUEST appends rejection reason to NEW_VALUE for full audit trail.
LOG_AUDIT uses `PRAGMA AUTONOMOUS_TRANSACTION` — audit never affects caller transaction.

**ACCOUNT_PKG — Gap G1 (open)**
CREATE_ACCOUNT hardcodes BILLING_CYCLE='MONTHLY'.
MCP server will accept billing_cycle param and pass via direct INSERT if cycle != MONTHLY.

**BILLING_PKG — Gap G3 (open)**
GENERATE_BILL auto-generates INVOICE_NUMBER.
MCP server post-queries BILL_SUMMARY after execution to retrieve and return generated number.

---

## 9. Tool Catalogue — 80 Tools

### Group A — Provider & Invoicing Company (5)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_providers` | READ | Direct SQL on PROVIDER |
| `get_provider_details` | READ | Direct SQL |
| `get_invoicing_companies` | READ | Direct SQL |
| `create_provider` | WRITE | Approval → Direct INSERT |
| `update_provider_status` | WRITE | Approval → Direct UPDATE |

### Group B — Customer (8)
| Tool | Type | Oracle Call |
|---|---|---|
| `search_customers` | READ | Direct SQL with LIKE |
| `get_customer_by_number` | READ | CUSTOMER_PKG.GET_CUSTOMER_DETAILS |
| `get_customer_360` | READ | Multi-table JOIN |
| `get_customers_by_company` | READ | Direct SQL |
| `get_customer_summary_stats` | READ | Aggregation SQL |
| `get_customer_types` | READ | Direct SQL on CUSTOMER_TYPE |
| `create_customer` | WRITE | Approval → CUSTOMER_PKG.CREATE_CUSTOMER |
| `update_customer_status` | WRITE | Approval → CUSTOMER_PKG.UPDATE_CUSTOMER_STATUS |

### Group C — Address & Contact (6)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_customer_addresses` | READ | JOIN ADDRESS |
| `get_customer_contacts` | READ | JOIN CONTACT + CONTACT_DETAILS |
| `search_contacts_by_email` | READ | Direct SQL LIKE |
| `add_customer_address` | WRITE | Approval → Direct INSERT |
| `add_customer_contact` | WRITE | Approval → Direct INSERT x2 |
| `update_contact_email` | WRITE | Approval → Direct UPDATE |

### Group D — Account (9)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_accounts_by_customer` | READ | JOIN ACCOUNT + ACCOUNT_DETAILS |
| `get_account_details` | READ | ACCOUNT_PKG.GET_ACCOUNT_DETAILS |
| `get_accounts_by_currency` | READ | Direct SQL |
| `get_account_commissioning_info` | READ | Direct SQL on ACCOUNT_DETAILS |
| `get_accounts_by_billing_cycle` | READ | Direct SQL |
| `get_accounts_pending_termination` | READ | TERMINATION_DATE <= SYSDATE+N |
| `create_account` | WRITE | Approval → ACCOUNT_PKG.CREATE_ACCOUNT |
| `update_account_status` | WRITE | Approval → ACCOUNT_PKG.UPDATE_ACCOUNT_STATUS |
| `set_account_billable` | WRITE | Approval → Direct UPDATE ACCOUNT_DETAILS |

### Group E — Product (5)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_products` | READ | Direct SQL on PRODUCT |
| `get_product_by_code` | READ | Direct SQL |
| `get_customer_products` | READ | JOIN CPD + PRODUCT |
| `assign_product_to_account` | WRITE | Approval → Direct INSERT |
| `terminate_customer_product` | WRITE | Approval → Direct UPDATE |

### Group F — Billing & Invoice (10)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_bills_by_account` | READ | BILLING_PKG.GET_BILL_DETAILS |
| `get_bill_by_invoice_number` | READ | Direct SQL |
| `get_billing_summary_by_customer` | READ | Aggregation SQL |
| `get_unpaid_bills` | READ | Direct SQL |
| `get_monthly_revenue` | READ | Aggregation + GROUP BY |
| `get_revenue_by_product_type` | READ | Multi-table JOIN + GROUP BY |
| `get_pending_adjustments` | READ | BILLING_ADJUSTMENT_PKG.GET_PENDING_ADJUSTMENTS |
| `create_bill` | WRITE | Approval → BILLING_PKG.GENERATE_BILL |
| `update_bill_status` | WRITE | Approval → BILLING_PKG.UPDATE_BILL_STATUS |
| `create_billing_adjustment` | WRITE | Approval → BILLING_ADJUSTMENT_PKG.CREATE_ADJUSTMENT |

### Group G — Costed Events / Usage Analytics (8)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_events_by_account` | READ | USAGE_ANALYTICS_PKG.GET_ACCOUNT_USAGE |
| `get_event_summary` | READ | Direct SQL + aggregation |
| `get_top_usage_accounts` | READ | USAGE_ANALYTICS_PKG.GET_TOP_BANDWIDTH_ACCOUNTS |
| `get_events_by_source_system` | READ | Direct SQL |
| `get_bandwidth_trend` | READ | Direct SQL + TRUNC(EVENT_DTM) |
| `get_failed_events` | READ | STATUS != 'SUCCESS' |
| `get_usage_anomalies` | READ | USAGE_ANALYTICS_PKG.GET_USAGE_ANOMALIES |
| `ingest_costed_event` | WRITE | Approval → Direct INSERT |

### Group H — Daily Load Monitoring (4) ✅ NEW
| Tool | Type | Oracle Call |
|---|---|---|
| `get_load_status_today` | READ | LOAD_MONITOR_PKG.GET_LOAD_STATUS |
| `get_missing_loads` | READ | LOAD_MONITOR_PKG.GET_MISSING_LOADS |
| `get_load_history` | READ | LOAD_MONITOR_PKG.GET_LOAD_HISTORY |
| `get_failed_load_summary` | READ | LOAD_MONITOR_PKG.GET_FAILED_LOAD_SUMMARY |

### Group I — Service Request / RCA Tickets (6) ✅ NEW
| Tool | Type | Oracle Call |
|---|---|---|
| `get_open_requests` | READ | SERVICE_REQUEST_PKG.GET_OPEN_REQUESTS |
| `get_requests_by_customer` | READ | SERVICE_REQUEST_PKG.GET_REQUESTS_BY_CUSTOMER |
| `create_service_request` | WRITE | Approval → SERVICE_REQUEST_PKG.CREATE_REQUEST |
| `assign_service_request` | WRITE | Approval → SERVICE_REQUEST_PKG.ASSIGN_REQUEST |
| `resolve_service_request` | WRITE | Approval → SERVICE_REQUEST_PKG.RESOLVE_REQUEST |
| `add_customer_note` | WRITE | Approval → Direct INSERT on CUSTOMER_NOTE |

### Group J — Currency & Reference Data (3)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_currencies` | READ | Direct SQL on CURRENCY |
| `get_currency_by_code` | READ | Direct SQL |
| `create_currency` | WRITE | Approval → Direct INSERT |

### Group K — Audit & Approval Management (6)
| Tool | Type | Oracle Call |
|---|---|---|
| `get_pending_approvals` | READ | Direct SQL on MCP_APPROVAL_REQUEST |
| `get_my_pending_requests` | READ | Direct SQL on MCP_APPROVAL_REQUEST |
| `get_audit_log` | READ | Direct SQL on MCP_AUDIT_LOG |
| `get_audit_stats` | READ | Aggregation on MCP_AUDIT_LOG |
| `approve_request` | WRITE | MCP_SECURITY_PKG.APPROVE_REQUEST |
| `reject_request` | WRITE | MCP_SECURITY_PKG.REJECT_REQUEST |

### Group L — Schema Introspection (8)
| Tool | Type | Oracle Call |
|---|---|---|
| `list_tables` | READ | ALL_TABLES + COUNT(*) |
| `describe_table` | READ | ALL_TAB_COLUMNS + ALL_CONSTRAINTS |
| `list_packages` | READ | METADATA_PKG.LIST_PACKAGES |
| `list_package_procedures` | READ | METADATA_PKG.LIST_PACKAGE_PROCEDURES |
| `get_procedure_signature` | READ | METADATA_PKG.GET_PACKAGE_ARGUMENTS |
| `list_sequences` | READ | ALL_SEQUENCES |
| `list_indexes` | READ | ALL_INDEXES |
| `find_procedure_for_table` | READ | ALL_SOURCE text search |

### Group M — Cross-Entity Power Queries (6)
| Tool | Type | Oracle Call |
|---|---|---|
| `search_globally` | READ | UNION across 4 tables |
| `get_customer_health_check` | READ | 5 sub-queries |
| `get_inactive_entities` | READ | Direct SQL |
| `get_expiring_products` | READ | Direct SQL on CPD |
| `get_full_hierarchy` | READ | Recursive JOIN |
| `get_accounts_no_events` | READ | LEFT JOIN COSTED_EVENT IS NULL |

---

## 10. Agent Catalogue — 12 Sub-Agents

| # | Agent | Master | Tools Chained | Claude API |
|---|---|---|---|---|
| 1 | `customer_read_agent` | READ | 11 tools | No |
| 2 | `billing_read_agent` | READ | 8 tools | No |
| 3 | `usage_read_agent` | READ | 7 tools | No |
| 4 | `operations_read_agent` | READ | 8 tools | No |
| 5 | `rca_agent` | READ | 8 tools | Yes |
| 6 | `schema_agent` | READ | 8 tools | No |
| 7 | `insight_agent` | READ | 5 tools | Yes |
| 8 | `dml_agent` | WRITE | All write tools | No |
| 9 | `approval_agent` | WRITE | 6 tools | No |
| 10 | `onboarding_agent` | WRITE | 5 write tools | No |
| 11 | `billing_run_agent` | WRITE | Batch create_bill | No |
| 12 | `adjustment_agent` | WRITE | 2 tools | No |

---

## 11. Approval & Audit Framework

### Why Every Write Goes Through Approval

TCL finance data is sensitive. A wrong DML on BILL_SUMMARY or ACCOUNT can impact
customer invoices worth thousands. The framework ensures:
- No accidental DML — every write staged as PENDING first
- Full trail — who requested, who approved, what changed (OLD_VALUE vs NEW_VALUE)
- Rollback visibility — REJECTED requests record reason permanently
- No-op detection (all write types) — a write checks first and stages nothing
  when there is nothing to do, returning `{status:"NO_CHANGE", no_change:true}`:
  * UPDATEs (status/flag/email/assignment) already at the target value;
  * CREATEs of a key-unique record that already exists (currency, provider);
  * a product already actively assigned, or already terminated;
  * a service request already assigned to that user, or already resolved.
  For real UPDATEs the current value is captured in OLD_VALUE and the response
  includes `current_value`/`requested_value` so clients can show "from X to Y"
  before asking for confirmation.

### Approval Flow

```
User: "Update bill INV-8821 to PAID"
         │
         ▼
   [dml_agent receives]
         │
         ▼
   Zod Validation → FAIL → return error (no DB touch)
         │ PASS
         ▼
   Resolve INV-8821 → bill_summary_id = 551
         │
         ▼
   MCP_SECURITY_PKG.CREATE_APPROVAL_REQUEST(
       'BILLING_PKG', 'UPDATE_BILL_STATUS', 'UPDATE',
       current_status, '{"bill_summary_id":551,"status":"PAID"}',
       'requesting_user'
   )
         │
         ▼
   Return { request_id: 42, status: 'PENDING',
            summary: 'Update INV-8821 STATUS from UNPAID to PAID' }

--- User calls approve_request(42, 'john.doe') ---

         │
         ▼
   MCP_SECURITY_PKG.APPROVE_REQUEST(42, 'john.doe')
   → Validates PENDING, locks row, sets APPROVED
         │
         ▼
   BILLING_PKG.UPDATE_BILL_STATUS(551, 'PAID')
         │
   SUCCESS → Return { success: true, invoice: 'INV-8821', new_status: 'PAID' }
   FAIL    → STATUS='FAILED', return Oracle error message
```

### Audit Log — Every Tool Call Logged

| Field | Value |
|---|---|
| TOOL_NAME | Tool or agent name |
| PACKAGE_NAME | Oracle package called |
| PROCEDURE_NAME | Oracle procedure called |
| ACTION_TYPE | READ / INSERT / UPDATE / DELETE |
| REQUEST_PAYLOAD | JSON of input parameters |
| STATUS | SUCCESS / ERROR / STARTED |
| ERROR_MESSAGE | Oracle error if STATUS=ERROR |
| CREATED_BY | SYS_CONTEXT('USERENV','SESSION_USER') |
| CREATED_DTM | SYSTIMESTAMP |

---

## 12. ID Resolution Layer

Oracle procedures use numeric IDs. MCP tools accept business codes.
Resolvers bridge this transparently before any DB call.

### File: `src/db/resolvers.ts`

| Function | Input Example | Output | Table |
|---|---|---|---|
| `resolveCustomerNumber(num)` | 'CUST-001' | customer_id NUMBER | CUSTOMER |
| `resolveCompanyCode(code)` | 'EMEA-01' | inv_company_id NUMBER | INVOICING_COMPANY |
| `resolveCurrencyCode(code)` | 'USD' | currency_id NUMBER | CURRENCY |
| `resolveAccountNumber(num)` | 'ACC-8821' | account_id NUMBER | ACCOUNT |
| `resolveProductCode(code)` | 'PROD-MPLS' | product_id NUMBER | PRODUCT |
| `resolveProviderCode(code)` | 'TCL-MAIN' | provider_id NUMBER | PROVIDER |
| `resolveCustomerTypeCode(code)` | 'ENTERPRISE' | customer_type_id NUMBER | CUSTOMER_TYPE |

All resolvers are case-insensitive. On failure throws:
`"Customer 'CUST-999' not found"` — surfaces before any DB write.

---

## 13. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Single-entity read response | < 2 seconds |
| Aggregation / report response | < 10 seconds |
| Agent multi-tool chain response | < 30 seconds |
| rca_agent / insight_agent (Claude API) | < 60 seconds |
| Connection pool | min=2, max=10, increment=1 |
| Default rows per list tool | 50 |
| Maximum rows per list tool | 500 |
| Input validation | Zod schema on every tool before any DB call |
| SQL injection protection | Bind variables — zero string concatenation |
| Success response format | { success: true, data: any, row_count?: number } |
| Error response format | { success: false, error_code: string, message: string } |
| Audit coverage | 100% — every tool and agent call logged |
| Query timeout | 30 seconds |

---

## 14. Known Gaps & Fixes

| # | Gap | Status | Fix |
|---|---|---|---|
| G1 | CREATE_ACCOUNT hardcodes BILLING_CYCLE='MONTHLY' | 🔲 Open | MCP server passes billing_cycle via direct INSERT if != MONTHLY |
| G2 | GENERATE_BILL hardcodes BILLING_MONTH to current month | 🔲 Open | Post-execution SELECT returns billing_month actually used |
| G3 | GENERATE_BILL auto-generates INVOICE_NUMBER | 🔲 Open | Post-execution SELECT retrieves and returns generated number |
| G4 | All procedures take numeric IDs | 🔲 Open | Implement resolvers.ts in Task 03 |
| G5 | MCP_SECURITY_PKG missing APPROVE_REQUEST | ✅ Fixed | Fixed in Task 01 using PRAGMA EXCEPTION_INIT(-54) |
| G6 | MCP_SECURITY_PKG missing REJECT_REQUEST | ✅ Fixed | Fixed in Task 01 |
| G7 | METADATA_PKG body unconfirmed | ✅ Fixed | Confirmed — all 3 functions fully implemented |

---

## 15. DBeaver Tips — Lessons Learned

These were discovered during Task 01 execution. Important for all future tasks.

| Issue | Root Cause | Fix |
|---|---|---|
| `ORA-04063 package body has errors` | LOCK_TIMEOUT not a valid Oracle exception name | Use `PRAGMA EXCEPTION_INIT(E_ROW_LOCKED, -54)` |
| `PLS-00103 end-of-file at line N` | DBeaver cuts off large scripts at `/` delimiter | Run spec and body in **separate SQL editor tabs** |
| `ORA-00900 invalid SQL statement` | `/` after `END;` is SQL*Plus syntax, not DBeaver | Never use `/` in DBeaver SQL editor |
| `ORA-00905 missing keyword` | Running multiple BEGIN..END blocks together | Run **one block at a time**, Ctrl+Enter each |
| FK violation on smoke test | Passing numeric IDs as strings `'115'` instead of `115` | NUMBER params never use quotes |
| Smoke test partial failure | Running entire test script at once | Run each BEGIN..END block individually |

### Golden Rules for DBeaver

```
1. CREATE PACKAGE/PROCEDURE  → paste entire block → Execute SQL Script button
2. BEGIN...END block          → paste single block → Ctrl+Enter (NO slash)
3. SELECT statement           → Ctrl+Enter
4. Multiple statements        → separate tabs, one per execution
5. NUMBER parameters          → never use quotes: use 115 not '115'
6. PL/SQL errors              → SELECT LINE, TEXT FROM USER_ERRORS WHERE NAME='PKG_NAME'
```

---

## 16. Out of Scope v1

- DDL execution (CREATE TABLE, DROP, ALTER) via MCP tools
- Cross-schema queries — MCP_APP schema only
- Real-time streaming of COSTED_EVENT data
- Excel / PDF export from tool results
- Role-based access control per tool
- Oracle AWR / performance monitoring
- DBMS_SCHEDULER job management
- Multi-tenant / multi-schema support

---

## 17. Implementation Tasks with Unit Tests

---

### ✅ TASK 01 — Oracle Schema Enhancements — COMPLETE

**What was built:**
- 4 new tables: DAILY_LOAD_LOG, SERVICE_REQUEST, BILLING_ADJUSTMENT, CUSTOMER_NOTE
- 4 new sequences: SEQ_DAILY_LOAD_LOG, SEQ_SERVICE_REQUEST, SEQ_BILLING_ADJUSTMENT, SEQ_CUSTOMER_NOTE
- Fixed MCP_SECURITY_PKG: added APPROVE_REQUEST + REJECT_REQUEST (G5 & G6)
- New package: LOAD_MONITOR_PKG (6 procedures/functions)
- New package: SERVICE_REQUEST_PKG (7 procedures/functions)
- New package: BILLING_ADJUSTMENT_PKG (7 procedures/functions)

**Verified Results:**
```
Tables         : 20  ✅
Sequences      : 19  ✅
Packages       : 9   ✅ (all VALID)
Package Bodies : 9   ✅ (all VALID)
Indexes        : 50  ✅
```

**Issues encountered & resolved:**
- LOCK_TIMEOUT exception → fixed with PRAGMA EXCEPTION_INIT(-54)
- PLS-00103 end-of-file → fixed by separating spec and body into separate tabs
- ORA-00900 invalid statement → fixed by removing `/` from DBeaver scripts
- ORA-00905 missing keyword → fixed by running one BEGIN..END at a time

**Unit Tests — All Passed:**
```
✅ T01-01: 20 tables exist in USER_TABLES
✅ T01-02: 19 sequences exist in USER_SEQUENCES
✅ T01-03: 9 packages + 9 package bodies all STATUS='VALID'
✅ T01-04: MCP_SECURITY_PKG.APPROVE_REQUEST compiles — no errors
✅ T01-05: MCP_SECURITY_PKG.REJECT_REQUEST compiles — no errors
✅ T01-06: SERVICE_REQUEST FK to CUSTOMER and ACCOUNT both work
✅ T01-07: BILLING_ADJUSTMENT FK to BILL_SUMMARY and ACCOUNT both work
✅ T01-08: MCP_SECURITY_PKG.LOG_AUDIT inserts row in MCP_AUDIT_LOG
✅ T01-09: MCP_SECURITY_PKG.CREATE_APPROVAL_REQUEST creates PENDING row
✅ T01-10: SERVICE_REQUEST_PKG.CREATE_REQUEST → ASSIGN_REQUEST → RESOLVE_REQUEST flow works
✅ T01-11: 50 indexes created across all tables
```

---

### 🔲 TASK 02 — Node.js Project Scaffold & Oracle Connection

**Deliverables:**
```
tcl-mcp-server/
├── package.json
├── tsconfig.json
├── .env                  (DB_USER, DB_PASSWORD, DB_CONNECT_STRING, ANTHROPIC_API_KEY)
├── src/
│   ├── index.ts          ← MCP Server entry point, stdio transport
│   ├── db/
│   │   ├── pool.ts       ← Oracle connection pool min=2 max=10
│   │   └── resolvers.ts  ← 7 ID resolver stubs
│   └── utils/
│       ├── audit.ts      ← calls MCP_SECURITY_PKG.LOG_AUDIT
│       └── errors.ts     ← Oracle error code → human message
```

**Unit Tests TASK-02:**
```
🔲 T02-01: pool.ts — getConnection() returns valid Oracle connection
🔲 T02-02: pool.ts — pool never exceeds max=10 connections under load
🔲 T02-03: pool.ts — pool.close() on SIGINT completes without hanging
🔲 T02-04: .env — all 4 variables load correctly
🔲 T02-05: audit.ts — inserts row into MCP_AUDIT_LOG, returns AUDIT_ID > 0
🔲 T02-06: audit.ts — DB failure does not crash main server process
🔲 T02-07: errors.ts — ORA-00001 maps to "Duplicate value already exists"
🔲 T02-08: errors.ts — ORA-02291 maps to "Referenced entity does not exist"
🔲 T02-09: errors.ts — ORA-01400 maps to "Required field cannot be empty"
🔲 T02-10: index.ts — MCP server starts without throwing
```

---

### 🔲 TASK 03 — ID Resolver Helpers

**Deliverables:** Complete `src/db/resolvers.ts` with all 7 resolvers

**Unit Tests TASK-03:**
```
🔲 T03-01: resolveCustomerNumber returns correct CUSTOMER_ID
🔲 T03-02: resolveCustomerNumber('NONEXISTENT') throws human-readable error
🔲 T03-03: resolveCompanyCode returns correct INV_COMPANY_ID
🔲 T03-04: resolveCurrencyCode returns correct CURRENCY_ID
🔲 T03-05: resolveAccountNumber returns correct ACCOUNT_ID
🔲 T03-06: resolveProductCode returns correct PRODUCT_ID
🔲 T03-07: resolveProviderCode returns correct PROVIDER_ID
🔲 T03-08: resolveCustomerTypeCode returns correct CUSTOMER_TYPE_ID
🔲 T03-09: All resolvers case-insensitive — 'usd' same as 'USD'
🔲 T03-10: Error message includes the invalid value
```

---

### 🔲 TASK 04 — Schema Introspection Tools (Group L)

**Deliverables:** All 8 tools in Group L registered on MCP server

**Unit Tests TASK-04:**
```
🔲 T04-01: list_tables returns 20 tables with row counts
🔲 T04-02: describe_table('CUSTOMER') returns all 7 columns with types
🔲 T04-03: describe_table('NONEXISTENT') returns structured not-found
🔲 T04-04: list_packages returns all 9 packages
🔲 T04-05: list_package_procedures('BILLING_PKG') returns 3 procedures
🔲 T04-06: get_procedure_signature('BILLING_PKG','GENERATE_BILL') returns 4 params
🔲 T04-07: list_sequences returns 19 sequences
🔲 T04-08: list_indexes('ACCOUNT') returns all indexes on ACCOUNT
🔲 T04-09: find_procedure_for_table('BILL_SUMMARY') returns BILLING_PKG + lines
🔲 T04-10: Every tool call creates one row in MCP_AUDIT_LOG
```

---

### 🔲 TASK 05 — Reference & Lookup Read Tools

**Deliverables:** get_providers, get_provider_details, get_invoicing_companies,
get_currencies, get_currency_by_code, get_customer_types

**Unit Tests TASK-05:**
```
🔲 T05-01: get_providers status='ACTIVE' returns only ACTIVE rows
🔲 T05-02: get_providers status='ALL' returns all providers
🔲 T05-03: get_provider_details with valid code returns full record
🔲 T05-04: get_provider_details unknown code returns not-found message
🔲 T05-05: get_invoicing_companies country filter works correctly
🔲 T05-06: get_currencies returns array (empty array not error)
🔲 T05-07: get_currency_by_code('USD') returns correct CURRENCY_NAME
🔲 T05-08: get_currency_by_code('ZZZ') returns not-found message
🔲 T05-09: get_customer_types returns all rows from CUSTOMER_TYPE
🔲 T05-10: All 6 tools write audit log with ACTION_TYPE='READ'
```

---

### 🔲 TASK 06 — Customer Read Tools (Group B read)

**Deliverables:** search_customers, get_customer_by_number, get_customer_360,
get_customers_by_company, get_customer_summary_stats

**Unit Tests TASK-06:**
```
🔲 T06-01: search_customers name match is case-insensitive LIKE
🔲 T06-02: search_customers no params returns up to 50 rows default
🔲 T06-03: search_customers limit=10 returns exactly 10 rows
🔲 T06-04: search_customers limit=10 offset=10 returns next page
🔲 T06-05: get_customer_by_number returns CUSTOMER_TYPE_NAME and COMPANY_NAME joined
🔲 T06-06: get_customer_360 returns { customer, addresses[], contacts[], accounts[], products[], latest_bill }
🔲 T06-07: get_customer_360 unknown customer returns structured not-found
🔲 T06-08: get_customers_by_company returns only customers for that COMPANY_CODE
🔲 T06-09: get_customer_summary_stats returns { total, active, inactive, by_type[] }
```

---

### 🔲 TASK 07 — Address, Contact, Account Read Tools

**Deliverables:** All read tools in Groups C and D

**Unit Tests TASK-07:**
```
🔲 T07-01: get_customer_addresses returns all ADDRESS fields
🔲 T07-02: get_customer_addresses no address → empty array not error
🔲 T07-03: get_customer_contacts returns CONTACT joined with CONTACT_DETAILS
🔲 T07-04: search_contacts_by_email pattern returns matching contacts
🔲 T07-05: get_accounts_by_customer returns ACCOUNT joined with ACCOUNT_DETAILS + CURRENCY
🔲 T07-06: get_accounts_by_customer status='ACTIVE' filters correctly
🔲 T07-07: get_account_details calls ACCOUNT_PKG.GET_ACCOUNT_DETAILS
🔲 T07-08: get_account_commissioning_info null TERMINATION_DATE returned as null
🔲 T07-09: get_accounts_by_billing_cycle('MONTHLY') filters correctly
🔲 T07-10: get_accounts_pending_termination(30) returns correct date range
```

---

### 🔲 TASK 08 — Product & Billing Read Tools

**Deliverables:** All read tools in Groups E and F

**Unit Tests TASK-08:**
```
🔲 T08-01: get_products product_type filter returns correct subset
🔲 T08-02: get_customer_products returns START_DATE, END_DATE, STATUS
🔲 T08-03: get_bills_by_account calls BILLING_PKG.GET_BILL_DETAILS
🔲 T08-04: get_bills_by_account date range filters on BILLING_MONTH
🔲 T08-05: get_bill_by_invoice_number returns exact match or not-found
🔲 T08-06: get_billing_summary_by_customer returns SUM(TOTAL_AMOUNT)
🔲 T08-07: get_unpaid_bills excludes PAID and CANCELLED
🔲 T08-08: get_monthly_revenue returns month + total ordered by month DESC
🔲 T08-09: get_revenue_by_product_type joins correctly
🔲 T08-10: get_pending_adjustments returns only STATUS='PENDING'
```

---

### 🔲 TASK 09 — Usage Analytics & Operations Read Tools

**Deliverables:** All read tools in Groups G, H, and I

**Unit Tests TASK-09:**
```
🔲 T09-01: get_events_by_account resolves account_number before calling package
🔲 T09-02: get_events_by_account date range uses TIMESTAMP bind variables
🔲 T09-03: get_event_summary returns { total_in_bits, total_out_bits, avg_speed_mbps, event_count }
🔲 T09-04: get_top_usage_accounts calls GET_TOP_BANDWIDTH_ACCOUNTS with limit
🔲 T09-05: get_usage_anomalies(100) returns accounts where SPEED_MBPS > 100
🔲 T09-06: get_bandwidth_trend('DAY') groups by TRUNC(EVENT_DTM,'DD')
🔲 T09-07: get_bandwidth_trend('MONTH') groups by TRUNC(EVENT_DTM,'MM')
🔲 T09-08: get_failed_events returns STATUS != 'SUCCESS' only
🔲 T09-09: get_load_status_today returns one row per source system
🔲 T09-10: get_load_status_today empty array if no loads today
🔲 T09-11: get_missing_loads(7) returns systems absent in last 7 days
🔲 T09-12: get_open_requests returns OPEN and IN_PROGRESS only
🔲 T09-13: get_requests_by_customer filters by CUSTOMER_ID correctly
```

---

### 🔲 TASK 10 — Cross-Entity Power Query Tools (Group M)

**Unit Tests TASK-10:**
```
🔲 T10-01: search_globally searches CUSTOMER_NAME, ACCOUNT_NUMBER, EMAIL, INVOICE_NUMBER
🔲 T10-02: search_globally results include entity_type label
🔲 T10-03: get_customer_health_check flags missing_address correctly
🔲 T10-04: get_customer_health_check flags no_active_products correctly
🔲 T10-05: get_customer_health_check flags unpaid_bills correctly
🔲 T10-06: get_customer_health_check flags no_events_this_month correctly
🔲 T10-07: get_inactive_entities returns INACTIVE customers + accounts
🔲 T10-08: get_expiring_products(30) returns correct date window
🔲 T10-09: get_full_hierarchy returns nested JSON tree
🔲 T10-10: get_accounts_no_events returns accounts with no events this month
```

---

### 🔲 TASK 11 — Approval Workflow Engine

**Pre-requisite:** Task 01 must be complete (MCP_SECURITY_PKG G5/G6 fixed ✅)

**Unit Tests TASK-11:**
```
🔲 T11-01: Any write tool returns { request_id, status: 'PENDING' } — no DB change
🔲 T11-02: MCP_APPROVAL_REQUEST has new PENDING row with correct NEW_VALUE JSON
🔲 T11-03: approve_request executes DML — target table gains new row
🔲 T11-04: approve_request sets APPROVED, APPROVED_BY, APPROVED_DTM
🔲 T11-05: reject_request sets REJECTED — target table unchanged
🔲 T11-06: approve_request on APPROVED request returns ORA-20001
🔲 T11-07: approve_request on non-existent request returns ORA-20002
🔲 T11-08: get_pending_approvals returns only PENDING rows
🔲 T11-09: get_my_pending_requests filters by REQUESTED_BY
🔲 T11-10: approve_request audit log shows ACTION_TYPE='UPDATE' STATUS='SUCCESS'
🔲 T11-11: reject_request audit log shows STATUS='SUCCESS'
```

---

### 🔲 TASK 12 — All Write Tools

**Unit Tests TASK-12:**
```
🔲 T12-01: create_customer resolves company_code before approval
🔲 T12-02: create_customer unknown company_code fails at resolver
🔲 T12-03: create_account resolves customer_number + currency_code
🔲 T12-04: create_account after approval → ACTIVE, BILLING_CYCLE='MONTHLY'
🔲 T12-05: update_account_status resolves account_number before approval
🔲 T12-06: create_bill after approval → BILL_SUMMARY has auto-generated INVOICE_NUMBER
🔲 T12-07: create_bill server returns generated INVOICE_NUMBER to user
🔲 T12-08: update_bill_status PAID after approval → confirmed in DB
🔲 T12-09: assign_product_to_account resolves all 3 codes
🔲 T12-10: add_customer_address missing city fails Zod validation
🔲 T12-11: create_billing_adjustment negative amount fails Zod
🔲 T12-12: create_service_request after approval → STATUS='OPEN'
🔲 T12-13: create_currency duplicate code → approval executes → ORA-00001 mapped
```

---

### 🔲 TASK 13 — Error Handling, Pagination & Security

**Unit Tests TASK-13:**
```
🔲 T13-01: ORA-00001 → "Duplicate value already exists"
🔲 T13-02: ORA-02291 → "Referenced entity does not exist"
🔲 T13-03: ORA-01400 → "Required field cannot be empty"
🔲 T13-04: ORA-01403 → "No data found"
🔲 T13-05: SQL injection safely bound — no rows returned, no error
🔲 T13-06: limit=5 returns exactly 5 rows
🔲 T13-07: limit=5 offset=5 returns next page
🔲 T13-08: limit=501 capped to 500
🔲 T13-09: DB failure → structured error response, server stays up
🔲 T13-10: Query > 30s cancelled with timeout message
🔲 T13-11: Empty required Zod field fails before any DB call
```

---

### 🔲 TASK 14 — schema_agent

**Unit Tests TASK-14:**
```
🔲 T14-01: "list all packages" → calls list_packages → returns 9
🔲 T14-02: "what does BILLING_PKG contain" → calls list_package_procedures
🔲 T14-03: "parameters for GENERATE_BILL" → calls get_procedure_signature
🔲 T14-04: "which procedures touch BILL_SUMMARY" → calls find_procedure_for_table
🔲 T14-05: "describe customer table" → calls describe_table('CUSTOMER')
🔲 T14-06: "how are CUSTOMER and ACCOUNT related" → FK info returned
🔲 T14-07: audit log shows TOOL_NAME='schema_agent' for every call
```

---

### ✅ TASK 15 — customer_read_agent + billing_read_agent

**Unit Tests TASK-15:**
```
🔲 T15-01: "contact for CUST-100" → contact name + email + phone
🔲 T15-02: "active customers under EMEA-01" → get_customers_by_company(ACTIVE)
🔲 T15-03: "products expiring this month" → get_expiring_products(30)
🔲 T15-04: "health check for CUST-1042" → get_customer_health_check
🔲 T15-05: "unpaid bills in USD" → get_unpaid_bills(currency='USD')
🔲 T15-06: "who raised invoice INV-8821" → get_bill_by_invoice_number + CREATED_BY
🔲 T15-07: "due date for account ACC-001" → get_bills_by_account(UNPAID)
🔲 T15-08: "revenue for June 2026" → get_monthly_revenue with month filter
🔲 T15-09: "total outstanding in USD" → get_unpaid_bills + SUM TOTAL_AMOUNT
🔲 T15-10: Both agents log correct TOOL_NAME in audit
```

---

### ✅ TASK 16 — usage_read_agent + operations_read_agent

**Unit Tests TASK-16:**
```
🔲 T16-01: "usage for ACC-8821 this month" → get_events_by_account with date range
🔲 T16-02: "top 10 accounts by usage" → get_top_usage_accounts(10)
🔲 T16-03: "accounts exceeding 100 Mbps" → get_usage_anomalies(100)
🔲 T16-04: "failed events from MEDIATION today" → get_events_by_source_system + get_failed_events
🔲 T16-05: "bandwidth trend for ACC-001 by day" → get_bandwidth_trend('DAY')
🔲 T16-06: "did all systems send data today" → get_load_status_today
🔲 T16-07: "systems not loaded in 3 days" → get_missing_loads(3)
🔲 T16-08: "open tickets assigned to john.doe" → get_open_requests('john.doe')
🔲 T16-09: "accounts pending termination this week" → get_accounts_pending_termination(7)
🔲 T16-10: "data quality issues today" → get_failed_load_summary + get_accounts_no_events
```

---

### ✅ TASK 17 — rca_agent

**Unit Tests TASK-17:**
```
🔲 T17-01: unknown customer → stops with clear message at step 1
🔲 T17-02: calls get_bills_by_account for all accounts found
🔲 T17-03: calls get_event_summary for all accounts
🔲 T17-04: calls get_failed_events for all accounts
🔲 T17-05: calls get_load_status_today for source system health
🔲 T17-06: calls get_customer_health_check and includes flags
🔲 T17-07: sends all data to Claude API with structured prompt
🔲 T17-08: returns { customer_profile, billing_issues[], event_anomalies[], health_flags, rca_summary, recommended_actions[] }
🔲 T17-09: audit log shows all 7 sub-tool calls + Claude API call
🔲 T17-10: Claude API failure returns partial data + "AI summary unavailable"
🔲 T17-11: completes in < 60 seconds end to end
```

---

### ✅ TASK 18 — insight_agent

**Unit Tests TASK-18:**
```
🔲 T18-01: "Q1 2026 revenue" → calls get_monthly_revenue for Jan+Feb+Mar
🔲 T18-02: includes get_revenue_by_product_type breakdown
🔲 T18-03: includes get_top_usage_accounts(10)
🔲 T18-04: includes get_unpaid_bills total
🔲 T18-05: sends combined payload to Claude API
🔲 T18-06: returns { period, revenue_total, product_breakdown, top_accounts, outstanding, narrative }
🔲 T18-07: Claude API failure returns raw data + "narrative unavailable"
🔲 T18-08: audit log shows TOOL_NAME='insight_agent'
```

---

### ✅ TASK 19 — READ MASTER AGENT

**Unit Tests TASK-19:**
```
🔲 T19-01: "what parameters does GENERATE_BILL take" → schema_agent
🔲 T19-02: "who is the contact for CUST-100" → customer_read_agent
🔲 T19-03: "due date for account ACC-001" → billing_read_agent
🔲 T19-04: "failed events from MEDIATION" → usage_read_agent
🔲 T19-05: "did source systems send data today" → operations_read_agent
🔲 T19-06: "investigate CUST-1042 wrong invoice" → rca_agent
🔲 T19-07: "Q1 2026 executive revenue summary" → insight_agent
🔲 T19-08: ambiguous query → Claude API classifies correctly
🔲 T19-09: READ MASTER never executes INSERT/UPDATE/DELETE
🔲 T19-10: routing decision logged in audit
```

---

### ✅ TASK 20 — dml_agent + approval_agent

**Unit Tests TASK-20:**
```
🔲 T20-01: "update bill INV-8821 to PAID" → approval created, no DML yet
🔲 T20-02: "add address for CUST-1042" → resolves customer_number first
🔲 T20-03: dml_agent returns human-readable summary of change
🔲 T20-04: "show pending approvals" → get_pending_approvals
🔲 T20-05: "approve request 42" → approve_request(42) → DML executes
🔲 T20-06: "reject request 38 — duplicate" → reject_request with reason
🔲 T20-07: "show my pending requests" → get_my_pending_requests
🔲 T20-08: "delete all customers" → refused (no mass DELETE without WHERE)
🔲 T20-09: dml_agent logs TOOL_NAME='dml_agent' in audit
```

---

### ✅ TASK 21 — onboarding_agent

**Unit Tests TASK-21:**
```
🔲 T21-01: creates exactly 5 approval requests in correct order
🔲 T21-02: validates all inputs with Zod before creating any request
🔲 T21-03: returns checklist { step, description, request_id, status }[] for 5 steps
🔲 T21-04: resolves company_code before customer request
🔲 T21-05: resolves product_code before product assignment request
🔲 T21-06: invalid company_code fails at step 1 — no partial requests created
🔲 T21-07: after all 5 approvals → get_customer_360 returns complete record
🔲 T21-08: audit log shows all 5 sub-steps in sequence
```

---

### ✅ TASK 22 — billing_run_agent + adjustment_agent

**Unit Tests TASK-22:**
```
🔲 T22-01: gets all MONTHLY accounts for given month
🔲 T22-02: skips BILLABLE_FLAG='N' accounts with reason logged
🔲 T22-03: skips accounts with no events with reason logged
🔲 T22-04: flags anomaly accounts for manual review
🔲 T22-05: creates one approval per eligible account
🔲 T22-06: returns { total, queued, skipped, flagged, approval_ids[] }
🔲 T22-07: "apply credit 500 USD to INV-8821" → CREDIT adjustment approval
🔲 T22-08: "raise dispute for INV-9001" → DISPUTE adjustment approval
🔲 T22-09: "waive late fee for ACC-5501" → WAIVER adjustment approval
🔲 T22-10: negative amount fails Zod before approval
```

---

### ✅ TASK 23 — WRITE MASTER AGENT + INTENT ROUTER

**Unit Tests TASK-23:**
```
🔲 T23-01: "create customer Acme Corp" → WRITE → onboarding_agent
🔲 T23-02: "generate invoices for June" → WRITE → billing_run_agent
🔲 T23-03: "apply credit to INV-8821" → WRITE → adjustment_agent
🔲 T23-04: "approve request 42" → WRITE → approval_agent
🔲 T23-05: "update bill status to PAID" → WRITE → dml_agent
🔲 T23-06: "show unpaid bills in USD" → READ → billing_read_agent
🔲 T23-07: "investigate CUST-1042" → READ → rca_agent
🔲 T23-08: "what procedure creates a customer?" → READ → schema_agent
🔲 T23-09: WRITE MASTER never calls read-only tools directly
🔲 T23-10: READ MASTER never creates approval requests
🔲 T23-11: every routing decision logged in MCP_AUDIT_LOG
🔲 T23-12: ambiguous query → Claude API classifies → correct agent
```

---

### 🔲 TASK 24 — End-to-End Integration Test

**Scenario A: Full Onboarding**
```
🔲 T24-01: "Onboard Acme Corp under EMEA-01 with MPLS" → 5 pending approvals
🔲 T24-02: approve all 5 → complete onboarding in DB
🔲 T24-03: get_customer_360 → full profile returned
🔲 T24-04: health check → all green
```

**Scenario B: Billing Run**
```
🔲 T24-05: "Generate all monthly invoices for June 2026" → N approvals queued
🔲 T24-06: approve all → invoices created in BILL_SUMMARY
🔲 T24-07: "Revenue summary for June 2026" → insight_agent → narrative returned
```

**Scenario C: RCA Investigation**
```
🔲 T24-08: "Investigate CUST-1042 wrong bill" → rca_agent → full RCA report
🔲 T24-09: "Apply credit 500 USD to their invoice" → adjustment approval
🔲 T24-10: approve credit → BILLING_ADJUSTMENT applied to BILL_SUMMARY
🔲 T24-11: "Add RCA note to CUST-1042" → add_customer_note → approved → saved
```

**Scenario D: New Joiner Discovery**
```
🔲 T24-12: "What tables exist?" → schema_agent → 20 tables described
🔲 T24-13: "How are CUSTOMER and ACCOUNT related?" → FK explained
🔲 T24-14: "What procedure creates a customer?" → CUSTOMER_PKG.CREATE_CUSTOMER + params
🔲 T24-15: "Which procedures touch BILL_SUMMARY?" → BILLING_PKG + line numbers
```

**System Health**
```
🔲 T24-16: All operations have audit entries STATUS='SUCCESS'
🔲 T24-17: get_audit_stats shows correct call counts per tool
🔲 T24-18: No MCP_APPROVAL_REQUEST has STATUS='FAILED'
🔲 T24-19: Server process running after all ops (no memory leaks)
🔲 T24-20: get_customer_health_check all green for onboarded customer
```

---

## Summary

| Category | Count |
|---|---|
| Total MCP Tools | 80 |
| Tool Groups | 13 |
| Sub-Agents | 12 |
| Master Agents | 2 |
| Intent Router | 1 |
| Oracle Packages | 9 (6 existing + 3 new) |
| Tables | 20 (16 existing + 4 new) |
| Sequences | 19 (15 existing + 4 new) |
| Implementation Tasks | 24 |
| Unit Tests | 207 |
| Tasks Complete | 1 / 24 |
| Tasks Remaining | 23 / 24 |

---

*TCL Finance & Billing MCP Server — PRD v4.0*
*Task 01 Complete ✅ | Next: Task 02 — Node.js Project Scaffold*
