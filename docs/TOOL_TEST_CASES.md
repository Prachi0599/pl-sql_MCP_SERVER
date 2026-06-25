# Tool Test Cases — every tool, 5+ questions each

Test cases for **all 125 registered tools**. Each tool has a one-line purpose and
**at least 5 example questions** you can type into the **web UI** (`python web.py`)
or the **terminal chat** (`python chat.py`). Plain-English questions are routed by
the `ask` intent router to the right tool/agent; you don't call tools by name.

> **Seed identifiers** (adjust to your live data — some may have changed during
> testing): customer `CUST000122`, company `INV0001`, customer types
> `CORP/ENT/GOV/SMB/WHOLESALE`, product `PROD0048`, currency `USD`,
> an ACTIVE account (find one below), invoice `INV00000123`.
>
> Find live identifiers quickly:
> ```bash
> python -c "import asyncio; from src.tools.approval import _exec; from src.db.pool import get_connection,close_pool;
> async def m():
>  c=await get_connection();
>  print('account', (await _exec(c,\"SELECT ACCOUNT_NUMBER FROM MCP_APP.ACCOUNT WHERE STATUS='ACTIVE' FETCH FIRST 1 ROW ONLY\"))[0]);
>  print('invoice', (await _exec(c,'SELECT INVOICE_NUMBER FROM MCP_APP.BILL_SUMMARY FETCH FIRST 1 ROW ONLY'))[0]);
>  await c.close(); await close_pool()
> asyncio.run(m())"
> ```

> **Writes are approval-gated.** Every create/update/delete/DBA-maintenance tool
> **previews** the change and only applies it when you click **Approve** (web) or
> reply **yes** (terminal). To test safely without mutating seed data, reply
> **no / Cancel**, or use throwaway records.

---

## Group L — Schema Introspection (8 tools)

### list_tables
Purpose: list all tables in MCP_APP with row counts.
1. What tables are in the database?
2. List all tables with their row counts.
3. How many tables does the schema have?
4. Show me the database tables.
5. Which table has the most rows?

### describe_table
Purpose: columns + constraints of a table.
1. Describe the CUSTOMER table.
2. What columns does the ACCOUNT table have?
3. Show the structure of BILL_SUMMARY.
4. What are the constraints on the SERVICE_REQUEST table?
5. Describe the COSTED_EVENT table columns and keys.

### list_packages
Purpose: list PL/SQL packages.
1. What PL/SQL packages exist in the schema?
2. List all packages and their status.
3. Are all packages valid?
4. Show me the database packages.
5. How many packages are there?

### list_package_procedures
Purpose: procedures/functions in a package.
1. What procedures are in ACCOUNT_PKG?
2. List the procedures in BILLING_PKG.
3. Show the functions in USAGE_ANALYTICS_PKG.
4. What can CUSTOMER_PKG do?
5. List procedures in SERVICE_REQUEST_PKG.

### get_procedure_signature
Purpose: parameters of a specific procedure.
1. What parameters does ACCOUNT_PKG.CREATE_ACCOUNT take?
2. Show the signature of BILLING_PKG.GENERATE_BILL.
3. What arguments does CUSTOMER_PKG.UPDATE_CUSTOMER_STATUS need?
4. Parameters of SERVICE_REQUEST_PKG.CREATE_REQUEST?
5. Describe the inputs for BILLING_ADJUSTMENT_PKG.CREATE_ADJUSTMENT.

### list_sequences
Purpose: list sequences.
1. What sequences exist in the schema?
2. List all sequences and their last numbers.
3. Show the database sequences.
4. How many sequences are there?
5. What is the last number used by SEQ_CUSTOMER?

### list_indexes
Purpose: indexes for a table or all indexes.
1. List all indexes in the schema.
2. What indexes are on the ACCOUNT table?
3. Show indexes for BILL_SUMMARY.
4. Which columns are indexed on CUSTOMER?
5. Are there indexes on COSTED_EVENT?

### find_procedure_for_table
Purpose: package source lines referencing a table.
1. Which procedures reference the ACCOUNT table?
2. Where is BILL_SUMMARY used in PL/SQL code?
3. Find code that touches the CUSTOMER table.
4. What packages reference COSTED_EVENT?
5. Which procedures use SERVICE_REQUEST?

---

## Groups A & J — Reference & Lookup (6 tools)

### get_providers
Purpose: list providers by status.
1. List all active providers.
2. Show me every provider (active and inactive).
3. Which providers are inactive?
4. How many providers do we have?
5. Give me the provider list.

### get_provider_details
Purpose: one provider by code.
1. Show details for provider PROV001.
2. What is provider PROV002's service type?
3. Look up provider PROV003.
4. Give me the details of provider PROV001.
5. Is provider PROV002 active?

### get_invoicing_companies
Purpose: invoicing companies by country/status.
1. List all invoicing companies.
2. Which invoicing companies are in the US?
3. Show active invoicing companies.
4. How many invoicing companies are there?
5. List invoicing companies in India.

### get_currencies
Purpose: all currencies.
1. What currencies are supported?
2. List all currencies.
3. How many currencies do we have?
4. Show me the currency list.
5. Which currencies can accounts use?

### get_currency_by_code
Purpose: one currency by code.
1. Show details for currency USD.
2. What is the name of currency INR?
3. Look up the GBP currency.
4. Is EUR a supported currency?
5. Get currency USD.

### get_customer_types
Purpose: list customer types.
1. What customer types exist?
2. List all customer types.
3. Show the customer categories.
4. How many customer types are there?
5. What does the ENT customer type mean?

---

## Group B — Customer Read (5 tools)

### search_customers
Purpose: search customers by name/status (paginated).
1. Search for customers named "Enterprise".
2. Find customers with "Corp" in the name.
3. List active customers.
4. Show me 10 customers.
5. Find inactive customers named "Wholesale".

### get_customer_by_number
Purpose: one customer with type + company.
1. Show customer CUST000122.
2. What type is customer CUST000122?
3. Look up customer CUST000150.
4. Which company does CUST000122 belong to?
5. Get the details of customer CUST000122.

### get_customer_360
Purpose: full profile (addresses, contacts, accounts, products, latest bill).
1. Give me a 360 view of customer CUST000122.
2. Show the full profile for CUST000122.
3. Everything about customer CUST000122.
4. Show CUST000122's accounts, contacts and addresses.
5. What's the latest bill for customer CUST000122?

### get_customers_by_company
Purpose: customers for an invoicing company.
1. List customers for company INV0001.
2. Which customers belong to invoicing company INV0001?
3. Show active customers under INV0001.
4. How many customers does company INV0001 have?
5. Customers for company INV0001, please.

### get_customer_summary_stats
Purpose: totals + breakdown by type.
1. How many active customers do we have?
2. Give me customer totals.
3. Break down customers by type.
4. How many customers are inactive?
5. What's the split of customers across categories?

---

## Groups C & D — Address, Contact & Account Read (9 tools)

### get_customer_addresses
Purpose: a customer's addresses.
1. Show addresses for customer CUST000122.
2. What's the billing address of CUST000122?
3. List all addresses for CUST000122.
4. Where is customer CUST000122 located?
5. Does CUST000122 have a shipping address?

### get_customer_contacts
Purpose: a customer's contacts (with phone).
1. Show contacts for customer CUST000122.
2. Who are the contacts at CUST000122?
3. List phone numbers for CUST000122.
4. Give me the contact people for CUST000122.
5. What's the email of CUST000122's contact?

### search_contacts_by_email
Purpose: contacts matching an email pattern.
1. Find contacts with email containing "tcl".
2. Search contacts by email "admin".
3. Which contacts use a gmail address?
4. Look up contacts with "@enterprise" emails.
5. Find the contact with email "sam@globex.com".

### get_accounts_by_customer
Purpose: accounts for a customer (optional status).
1. List accounts for customer CUST000122.
2. How many accounts does CUST000122 have?
3. Show active accounts for CUST000122.
4. What accounts belong to customer CUST000122?
5. Show suspended accounts for CUST000122.

### get_account_details
Purpose: full account detail.
1. Show details for account ACC000124.
2. What's the status of account ACC000124?
3. Get account ACC000124.
4. Which currency does account ACC000124 use?
5. Full details of account ACC000124, please.

### get_accounts_by_currency
Purpose: accounts using a currency.
1. Which accounts use USD?
2. List accounts billed in INR.
3. Show active GBP accounts.
4. How many accounts use USD?
5. Find accounts in EUR.

### get_account_commissioning_info
Purpose: commissioning/termination dates.
1. When was account ACC000124 commissioned?
2. Show commissioning info for ACC000124.
3. Does account ACC000124 have a termination date?
4. When does account ACC000124 terminate?
5. Commissioning and termination dates for ACC000124?

### get_accounts_by_billing_cycle
Purpose: accounts by billing cycle.
1. List MONTHLY billing accounts.
2. Which accounts bill QUARTERLY?
3. Show active monthly-cycle accounts.
4. How many accounts are on a monthly cycle?
5. Find ANNUAL billing accounts.

### get_accounts_pending_termination
Purpose: accounts terminating within N days.
1. Which accounts are terminating in the next 30 days?
2. Show accounts pending termination.
3. Any accounts ending in the next 60 days?
4. Accounts due to terminate this week?
5. List upcoming account terminations.

---

## Groups E & F — Product & Billing Read (10 tools)

### get_products
Purpose: products by type/status.
1. List all active products.
2. Show me every product.
3. Which products are of type DATA?
4. How many products do we offer?
5. List inactive products.

### get_product_by_code
Purpose: one product by code.
1. Show product PROD0048.
2. What type is product PROD0048?
3. Look up product PROD0048.
4. Is product PROD0048 active?
5. Get details for PROD0048.

### get_customer_products
Purpose: products subscribed by a customer.
1. What products does customer CUST000122 have?
2. List active products for CUST000122.
3. Show subscriptions for customer CUST000122.
4. Which products has CUST000122 subscribed to?
5. Show terminated products for CUST000122.

### get_bills_by_account
Purpose: bills for an account (date/status filters).
1. Show bills for account ACC000124.
2. List unpaid bills for ACC000124.
3. What bills does account ACC000124 have this year?
4. Bills for ACC000124 between 2026-01-01 and 2026-06-30.
5. How many invoices does ACC000124 have?

### get_bill_by_invoice_number
Purpose: one bill by invoice.
1. Show invoice INV00000123.
2. What's the amount of invoice INV00000123?
3. Look up bill INV00000123.
4. Is invoice INV00000123 paid?
5. Get the details of invoice INV00000123.

### get_billing_summary_by_customer
Purpose: aggregated billing totals for a customer.
1. Give me a billing summary for customer CUST000122.
2. How much has CUST000122 been billed in total?
3. What's CUST000122's outstanding balance?
4. Total invoiced for customer CUST000122?
5. Billing overview for CUST000122.

### get_unpaid_bills
Purpose: unpaid (non-PAID/CANCELLED) bills.
1. Show all unpaid bills.
2. List overdue invoices.
3. Which bills are unpaid in USD?
4. How many invoices are outstanding?
5. Show the top unpaid bills.

### get_monthly_revenue
Purpose: monthly revenue totals.
1. Show monthly revenue for the last 6 months.
2. What was revenue last month?
3. Give me the revenue trend for 12 months.
4. How much did we bill each month this year?
5. Monthly revenue for the past quarter.

### get_revenue_by_product_type
Purpose: revenue split by product type.
1. Break down revenue by product type.
2. Which product type earns the most?
3. Show revenue per product category.
4. How much revenue comes from DATA products?
5. Revenue by product type, please.

### get_pending_adjustments
Purpose: pending billing adjustments.
1. List pending billing adjustments.
2. Are there any adjustments awaiting processing?
3. Show open credit/dispute adjustments.
4. How many adjustments are pending?
5. Pending adjustments overview.

---

## Groups G, H, I — Usage, Loads & Service Requests (13 tools)

### get_events_by_account
Purpose: costed events for an account.
1. Show usage events for account ACC000124.
2. List recent events for ACC000124.
3. Events for ACC000124 in June 2026.
4. How many usage events does ACC000124 have?
5. Show the latest 20 events for ACC000124.

### get_event_summary
Purpose: aggregated usage stats for an account.
1. Summarize usage for account ACC000124.
2. What's the average speed for ACC000124?
3. Total bits in/out for ACC000124?
4. Give me usage stats for ACC000124.
5. How many events and what bandwidth for ACC000124?

### get_top_usage_accounts
Purpose: top accounts by bandwidth.
1. Which accounts use the most bandwidth?
2. Show the top 5 usage accounts.
3. Top 10 accounts by data usage.
4. Who are our heaviest users?
5. Rank accounts by bandwidth.

### get_events_by_source_system
Purpose: events from a source system.
1. Show events from USAGE_COLLECTOR.
2. List failed events from source MEDIATION.
3. Events from source system USAGE_COLLECTOR.
4. How many events came from the collector?
5. Show successful events from USAGE_COLLECTOR.

### get_bandwidth_trend
Purpose: bandwidth trend by day/month.
1. Show the bandwidth trend by day.
2. Monthly bandwidth trend for account ACC000124.
3. How has usage trended over the last 30 days?
4. Daily bandwidth for the past month.
5. Bandwidth trend grouped by month.

### get_failed_events
Purpose: events with STATUS != SUCCESS.
1. Show failed usage events.
2. Which events failed?
3. List failed events from USAGE_COLLECTOR.
4. How many events failed recently?
5. Show the latest failed events.

### get_usage_anomalies
Purpose: events above a speed threshold.
1. Are there usage anomalies?
2. Show events faster than 100 Mbps.
3. Find unusually high-speed events.
4. List anomalies above 200 Mbps.
5. Any abnormal usage spikes?

### get_load_status_today
Purpose: today's pipeline load status.
1. What's today's data load status?
2. Did all source systems load today?
3. Show the pipeline status for today.
4. Are there any load failures today?
5. Today's load summary, please.

### get_missing_loads
Purpose: sources that haven't loaded in N days.
1. Which sources haven't loaded in the last 7 days?
2. Show missing data loads.
3. Any pipelines that stopped feeding data?
4. Missing loads in the past 3 days?
5. Which source systems are silent?

### get_load_history
Purpose: load history for a source system.
1. Show load history for USAGE_COLLECTOR.
2. How has MEDIATION loaded over 30 days?
3. Load history for source USAGE_COLLECTOR for the last week.
4. Did USAGE_COLLECTOR load consistently?
5. Past loads for source system USAGE_COLLECTOR.

### get_failed_load_summary
Purpose: failed-load summary per source.
1. Summarize failed loads in the last 7 days.
2. Which sources have the most load failures?
3. Failed load summary for the past week.
4. How many loads failed per source?
5. Show load-failure breakdown.

### get_open_requests
Purpose: open/in-progress service requests.
1. Show open service requests.
2. List unresolved tickets.
3. Which service requests are assigned to alice?
4. Show in-progress requests.
5. Open tickets with their assignee and description.

### get_requests_by_customer
Purpose: all service requests for a customer.
1. Show service requests for customer CUST000122.
2. What tickets has CUST000122 raised?
3. List all requests for customer CUST000122.
4. Any open issues for CUST000122?
5. Service request history for CUST000122.

---

## Group M — Cross-Entity Power Queries (6 tools)

### search_globally
Purpose: search customers/accounts/contacts/invoices at once.
1. Search globally for "Enterprise".
2. Find anything matching "ACC0001".
3. Global search for "INV00000".
4. Look up "globex" across the system.
5. Search everywhere for "CUST0001".

### get_customer_health_check
Purpose: health flags for a customer.
1. Run a health check on customer CUST000122.
2. Does CUST000122 have any unpaid bills?
3. Is customer CUST000122 missing an address or contact?
4. Health flags for CUST000122.
5. Any issues with customer CUST000122 this month?

### get_inactive_entities
Purpose: inactive customers/accounts.
1. Which customers are inactive?
2. List inactive accounts.
3. Show all inactive entities.
4. How many inactive customers are there?
5. Inactive accounts and customers, please.

### get_expiring_products
Purpose: products expiring within N days.
1. Which products expire in the next 30 days?
2. Show expiring subscriptions.
3. Any products ending in 60 days?
4. Products expiring this week?
5. Upcoming product expirations.

### get_full_hierarchy
Purpose: company→customer→accounts→products tree.
1. Show the full hierarchy for customer CUST000122.
2. Give me the company-to-products tree for CUST000122.
3. Nested view of CUST000122's accounts and products.
4. Full structure under customer CUST000122.
5. Hierarchy for CUST000122.

### get_accounts_no_events
Purpose: active accounts with no events this month.
1. Which active accounts have no usage this month?
2. Show accounts with no events.
3. Any billable accounts not sending data?
4. Active accounts missing usage this month.
5. List accounts with zero events.

---

## Group K — Approval & Audit (7 tools)

### get_pending_approvals
Purpose: all PENDING approval requests.
1. Show pending approvals.
2. What changes are awaiting approval?
3. List the approval queue.
4. How many requests are pending?
5. Pending approvals raised by mcp_user.

### get_my_pending_requests
Purpose: PENDING requests by a user.
1. Show my pending requests.
2. What's pending for user alice?
3. List requests raised by mcp_user awaiting approval.
4. Pending items for chat_user.
5. My approval queue.

### get_audit_log
Purpose: audit-log entries (tool/status filters).
1. Show the audit log.
2. List recent audit entries.
3. Show ERROR entries in the audit log.
4. Audit entries for the writes tool.
5. Last 50 audited actions.

### get_audit_stats
Purpose: per-tool call counts + success/error.
1. Show audit statistics.
2. Which tools are called most?
3. How many errors per tool?
4. Audit success/failure breakdown.
5. Tool usage stats.

### get_recent_changes
Purpose: recently APPROVED changes (cross-session).
1. What changes have been made recently?
2. Show the last applied changes.
3. List recently approved changes.
4. What was changed and by whom?
5. Recent change history.

### approve_request
Purpose: approve a PENDING request and run its DML.
1. Approve request 1001.
2. Approve approval #1002 as alice.
3. Apply the pending change with id 1003.
4. Go ahead and approve request 1004.
5. Approve request number 1005.

### reject_request
Purpose: reject a PENDING request (no DML).
1. Reject request 1001.
2. Reject approval #1002 with reason "duplicate".
3. Cancel pending request 1003.
4. Decline request 1004 as alice.
5. Reject request 1005, reason "not needed".

---

## Groups A–J — Write tools (22 tools)  *(approval-gated — preview then Approve)*

### create_provider
1. Create a provider PROVX1 called "Acme Telecom", type VOICE, country US.
2. Add a new provider "Globex Net" with code PROVX2 in India.
3. Register provider PROVX3, service DATA, country UK.
4. Set up a new telecom provider PROVX4.
5. Create provider PROVX5 "Test Carrier" type VOICE in CA.

### update_provider_status
1. Set provider PROV001 to INACTIVE.
2. Activate provider PROV002.
3. Deactivate provider PROV003.
4. Change provider PROV001 status to ACTIVE.
5. Mark provider PROV002 as inactive.

### create_customer
1. Create a customer "Acme Corp", company INV0001, type CORP.
2. Add a new ENT customer "Globex Ltd" under INV0001.
3. Register customer "Wayne Enterprises", company INV0001, type CORP.
4. New SMB customer "Small Biz Co" for company INV0001.
5. Create customer "Gov Agency", company INV0001, type GOV.

### update_customer_status
1. Set customer CUST000122 to INACTIVE.
2. Activate customer CUST000150.
3. Suspend customer CUST000122.
4. Change CUST000150 status to ACTIVE.
5. Mark customer CUST000122 as TERMINATED.

### add_customer_address
1. Add a billing address "1 Test St, Mumbai, IN" for customer CUST000122.
2. Add a shipping address for CUST000122 in Delhi.
3. Register a new address for customer CUST000150.
4. Add address "5 Market St, Pune, IN" for CUST000122.
5. Give customer CUST000122 a billing address in Bangalore.

### add_customer_contact
1. Add a contact "Sam Lee", Director, sam@x.com for CUST000122.
2. New contact for CUST000122: "Jo Tan", Manager, jo@x.com.
3. Add contact person "Pat Roy" with email pat@x.com to CUST000150.
4. Register a billing contact for customer CUST000122.
5. Add contact "Amy Singh", phone 9999999999, for CUST000122.

### update_contact_email
1. Update contact 10's email to new@x.com.
2. Change the email of contact 12 to admin@y.com.
3. Set contact 15's email to support@z.com.
4. Fix the email for contact id 20.
5. Update contact 25 email to ops@x.com.

### create_account
1. Create an account "Main Account" in USD for customer CUST000122.
2. Add a new INR account for CUST000150.
3. Open account "Ops Billing" for customer CUST000122 in USD.
4. New account for CUST000122 named "Secondary" in GBP.
5. Create a USD account "Globex Main" for CUST000122.

### update_account_status
1. Set account ACC000124 status to INACTIVE.
2. Activate account ACC000124.
3. Suspend account ACC000124.
4. Change account status to ACTIVE for customer CUST000150.
5. Mark account ACC000124 as SUSPENDED.

### set_account_billable
1. Make account ACC000124 billable.
2. Set account ACC000124 billable flag to N.
3. Stop billing account ACC000124.
4. Enable billing for ACC000124.
5. Set ACC000124 to non-billable.

### update_account_currency
1. Change account ACC000124 currency to INR.
2. Set ACC000124 to bill in USD.
3. Switch account ACC000124 to GBP.
4. Change the currency for customer CUST000150's account to USD.
5. Update ACC000124 currency to EUR.

### assign_product_to_account
1. Assign product PROD0048 to account ACC000124 for customer CUST000122.
2. Add product PROD0048 to CUST000122's account ACC000124.
3. Subscribe ACC000124 to product PROD0048.
4. Give customer CUST000122 product PROD0048 on ACC000124, starting 2026-07-01.
5. Provision PROD0048 on account ACC000124.

### terminate_customer_product
1. Terminate product PROD0048 for customer CUST000122.
2. End CUST000122's subscription to PROD0048.
3. Cancel product PROD0048 for CUST000122 as of 2026-12-31.
4. Stop product PROD0048 on customer CUST000122.
5. Terminate PROD0048 for CUST000122.

### create_bill
1. Generate a bill of 500 plus 50 tax in USD for account ACC000124.
2. Create an invoice for ACC000124: amount 1200, tax 120, USD.
3. Bill account ACC000124 for 300 + 30 tax in USD.
4. Raise a bill for ACC000124, 999 amount, 99 tax, USD.
5. Generate an invoice for ACC000124 in USD.

### update_bill_status
1. Mark invoice INV00000123 as PAID.
2. Set invoice INV00000123 to UNPAID.
3. Dispute invoice INV00000123.
4. Change bill INV00000123 status to PAID.
5. Cancel invoice INV00000123.

### create_billing_adjustment
1. Apply a $250 CREDIT to invoice INV00000123 for account ACC000124 due to an outage.
2. Waive 100 on invoice INV00000123 for ACC000124.
3. Raise a DISPUTE of 75 on INV00000123 for ACC000124.
4. Give a credit adjustment of 200 on invoice INV00000123.
5. Add a DEBIT of 50 to invoice INV00000123 for ACC000124.

### ingest_costed_event
1. Ingest a usage event for ACC000124 at 2026-06-26 10:00:00.
2. Add a costed event for account ACC000124 with 1000 in-bits.
3. Record usage for ACC000124: 2026-06-26 12:00:00, 50 Mbps.
4. Insert a data-usage event for ACC000124.
5. Log a costed event for ACC000124 from USAGE_COLLECTOR.

### create_service_request
1. Raise a HIGH priority billing service request for CUST000122: "invoice looks wrong", raised by alice.
2. Create a DATA_FIX ticket for CUST000122, priority MEDIUM, raised by bob.
3. Open an RCA request for customer CUST000122 raised by carol.
4. Log a LOW priority query for CUST000122 raised by dan.
5. New billing-adjustment request for CUST000122 raised by alice.

### assign_service_request
1. Assign request 41 to alice.
2. Give ticket 42 to bob.
3. Reassign service request 41 to carol.
4. Set the owner of request 42 to dan.
5. Assign request 41 to the billing team lead "eve".

### resolve_service_request
1. Resolve request 41 with notes "fixed billing error", resolved by alice.
2. Close ticket 42, resolution "duplicate", resolved by bob.
3. Mark service request 41 resolved by carol.
4. Resolve request 42 with notes "adjusted invoice".
5. Complete request 41, resolved by alice.

### add_customer_note
1. Add a GENERAL note "VIP customer" for CUST000122 created by alice.
2. Log a BILLING note on CUST000122 by bob.
3. Add an ESCALATION note for customer CUST000122 created by carol.
4. Note on CUST000122: "called about invoice", by dan.
5. Add a TECHNICAL note for CUST000122 created by eve.

### create_currency
1. Create a new currency GBP called "British Pound".
2. Add currency JPY "Japanese Yen".
3. Register currency AUD "Australian Dollar".
4. Create currency CAD called "Canadian Dollar".
5. Add a new currency CHF "Swiss Franc".

---

## Group L — Delete tools (6 tools)  *(approval-gated; hard deletes are irreversible)*

### delete_customer_note
1. Delete customer note 21.
2. Remove note 22.
3. Delete the note with id 23.
4. Get rid of customer note 24.
5. Delete note 25.

### delete_customer_address
1. Delete address 10.
2. Remove customer address 11.
3. Delete the address with id 12.
4. Get rid of address 13.
5. Delete customer address 14.

### delete_customer_contact
1. Delete contact 10.
2. Remove customer contact 11.
3. Delete the contact with id 12 (and its phone details).
4. Get rid of contact 13.
5. Delete customer contact 14.

### delete_costed_event
1. Delete costed event 5.
2. Remove usage event 6.
3. Delete the event with id 7.
4. Get rid of costed event 8.
5. Delete event 9.

### delete_account
1. Delete account ACC000130.  *(hard delete — removes its bills/events/products)*
2. Permanently remove account ACC000131.
3. Delete account ACC000132 and everything under it.
4. Hard-delete account ACC000133.
5. Remove account ACC000134 completely.

### delete_customer
1. Delete customer CUST000200.  *(hard delete — removes accounts, contacts, etc.)*
2. Permanently remove customer CUST000201.
3. Delete customer CUST000202 and all related records.
4. Hard-delete customer CUST000203.
5. Remove customer CUST000204 entirely.

---

## Group N — DBA / Database Administration (16 tools)

### get_database_health
1. Is the database healthy?
2. Give me a database health snapshot.
3. Are there any invalid objects?
4. How big is the schema?
5. Overall DB health check.

### get_active_sessions
1. How many sessions are connected?
2. Show active database sessions.
3. Who is connected to the database?
4. List current user sessions.
5. Show session activity.

### get_blocking_sessions
1. Are there any deadlocks or blocking sessions?
2. Show lock contention.
3. Is anything blocked right now?
4. Find blocking sessions.
5. Any database locks?

### get_slow_queries
1. What are the slowest queries?
2. Show top SQL by elapsed time.
3. Which queries need optimization?
4. Find slow-running statements.
5. Top 10 slowest queries.

### get_wait_events
1. Show the top database wait events.
2. What is the database waiting on?
3. Top wait events by time.
4. Show system waits.
5. Database wait analysis.

### get_tablespace_usage
1. Show tablespace usage.
2. How much space is used per tablespace?
3. Are any tablespaces nearly full?
4. Tablespace space report.
5. Disk usage by tablespace.

### get_segment_sizes
1. What are the largest segments?
2. Show the biggest tables and indexes.
3. Top 20 segments by size.
4. Which objects use the most space?
5. Segment size report.

### get_invalid_objects
1. Are there any invalid objects?
2. List INVALID packages or procedures.
3. Show objects that need recompiling.
4. Any broken database objects?
5. Invalid objects report.

### get_unused_indexes
1. Show me unused indexes I could remove.
2. Which indexes are candidates for removal?
3. Find non-constraint secondary indexes.
4. Remove unwanted indexing — what can go?
5. List review-candidate indexes.

### get_redundant_indexes
1. Are there redundant indexes?
2. Find indexes that duplicate others.
3. Show overlapping indexes.
4. Which indexes are a prefix of another?
5. Redundant index report.

### get_table_stats_status
1. Which tables have stale statistics?
2. Show tables needing a stats refresh.
3. Are optimizer stats up to date?
4. Find tables with missing stats.
5. Stale statistics report.

### get_long_operations
1. Are there long-running operations?
2. Show operations in progress.
3. Is anything causing a slowdown right now?
4. Long-running queries report.
5. Show V$ long operations.

### drop_index   *(approval-gated)*
1. Drop index IX_CUSTOMER_NAME.
2. Remove the unused index IX_ACCOUNT_STATUS.
3. Delete index IDX_BILL_DATE.
4. Drop the index IX_EVENT_DTM.
5. Remove index IX_CONTACT_EMAIL.

### rebuild_index   *(approval-gated)*
1. Rebuild index IX_CUSTOMER_NAME.
2. Defragment index IX_ACCOUNT_STATUS.
3. Rebuild the index IDX_BILL_DATE.
4. Re-cluster index IX_EVENT_DTM.
5. Rebuild index IX_CONTACT_EMAIL.

### gather_table_stats   *(approval-gated)*
1. Gather statistics for the CUSTOMER table.
2. Refresh stats on the ACCOUNT table.
3. Recompute optimizer statistics for BILL_SUMMARY.
4. Gather stats for COSTED_EVENT.
5. Update statistics on the SERVICE_REQUEST table.

### recompile_object   *(approval-gated)*
1. Recompile package ACCOUNT_PKG.
2. Recompile the invalid object BILLING_PKG.
3. Compile procedure CUSTOMER_PKG.
4. Recompile USAGE_ANALYTICS_PKG.
5. Recompile object SERVICE_REQUEST_PKG.

---

## Agents (17 tools)

### ask  *(primary entry point — routes everything)*
1. How many active customers do we have?
2. Investigate billing issues for customer CUST000122.
3. Set account ACC000124 status to INACTIVE.
4. What are the slowest queries?
5. Run the monthly billing for 2026-06.

### read_master_agent  *(routes any read)*
1. Show the monthly revenue for 6 months.
2. List unpaid bills.
3. Describe the ACCOUNT table.
4. Which accounts use USD?
5. How many active customers are there?

### query_data  *(universal text-to-SQL, read-only)*
1. Show account details for ACC000124.
2. List all account numbers.
3. Give me the top 5 customer ids.
4. What currency does customer CUST000122 use?
5. Which accounts are INACTIVE?

### write_master_agent  *(routes any write)*
1. Create a customer "Acme Corp", company INV0001, type CORP.
2. Set account ACC000124 to INACTIVE.
3. Apply a $100 credit to invoice INV00000123 for ACC000124.
4. Run billing for 2026-06.
5. Drop index IX_CONTACT_EMAIL.

### customer_read_agent
1. Look up customer CUST000122.
2. Show contacts for CUST000122.
3. How many active customers by type?
4. What products does CUST000122 have?
5. Show addresses for customer CUST000122.

### billing_read_agent
1. Show invoice INV00000123.
2. Unpaid bills for account ACC000124.
3. Billing summary for customer CUST000122.
4. Revenue for account ACC000124.
5. List pending adjustments.

### usage_read_agent
1. Top usage accounts this month.
2. Show failed events.
3. Usage summary for ACC000124.
4. Bandwidth trend by day.
5. Any usage anomalies above 100 Mbps?

### operations_read_agent
1. Today's load status.
2. Which sources are missing loads?
3. Show open service requests.
4. List inactive accounts.
5. Active accounts with no events this month.

### rca_agent  *(deep root-cause for one customer)*
1. Investigate billing and usage issues for customer CUST000122.
2. Diagnose problems for CUST000122.
3. Why is billing wrong for customer CUST000122?
4. Root-cause analysis for CUST000122.
5. Investigate customer CUST000122's account health.

### insight_agent  *(executive financial narrative)*
1. Give me an executive revenue summary.
2. How is revenue trending this year?
3. Which product types drive revenue?
4. Summarize outstanding payments.
5. Quarterly financial overview.

### schema_agent
1. What packages exist in the schema?
2. Describe the CUSTOMER table.
3. What parameters does CREATE_ACCOUNT take?
4. List all sequences.
5. What indexes are on BILL_SUMMARY?

### dml_agent  *(single natural-language write)*
1. Update customer CUST000122 status to ACTIVE.
2. Add a note "VIP" to customer CUST000122 by alice.
3. Delete costed event 9.
4. Create currency JPY "Japanese Yen".
5. Change account ACC000124 currency to INR.

### approval_agent  *(manage the approval queue)*
1. Show pending approvals.
2. Approve request 1001.
3. Reject request 1002 with reason "duplicate".
4. List the approval queue.
5. Approve approval #1003 as alice.

### onboarding_agent  *(full customer setup — 5 steps)*
1. Onboard a new customer "Globex Ltd", company INV0001, type CORP, address "5 Market St, Delhi, IN", contact "Sam Lee" Director sam@globex.com, account "Globex Main" in USD, product PROD0048.
2. Set up a brand-new ENT customer end-to-end under INV0001.
3. Onboard "Wayne Enterprises" with a USD account and product PROD0048.
4. Create a full new customer "Stark Industries" with contact and account.
5. Onboard customer "Acme Corp" (CORP, INV0001) with address, contact, USD account and PROD0048.

### billing_run_agent  *(monthly billing run)*
1. Run the monthly billing for 2026-06.
2. Execute billing for June 2026.
3. Generate this month's bills.
4. Run billing for 2026-05.
5. Kick off the monthly billing run for 2026-06.

### adjustment_agent  *(billing adjustment)*
1. Apply a $250 credit to invoice INV00000123 for ACC000124.
2. Waive 100 on invoice INV00000123.
3. Dispute 75 on invoice INV00000123 for ACC000124.
4. Refund 200 on invoice INV00000123.
5. Add a credit adjustment to invoice INV00000123 due to an outage.

### dba_agent  *(DBA diagnostics + maintenance)*
1. Is the database slow or unhealthy?
2. Show me unused indexes I could remove.
3. Which tables have stale statistics?
4. Gather statistics for the CUSTOMER table.
5. Are there any deadlocks or blocking sessions?

---

## Coverage

125 tools × ≥5 questions = **625+ test questions**. Pair this with:
- `docs/TEST_CASES_NEW_FEATURES.md` — focused validation of the recent features.
- `docs/TEST_QUESTIONS.txt` — the original per-tool bank.
- `python -m pytest tests/ -q` — the automated suite (unit + integration).
