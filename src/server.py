"""TCL Finance & Billing MCP Server — entry point.

Tools are registered here as each task is implemented.

Run either way (both work):
    python -m src.server          # run as a module from the project root
    python src/server.py          # run the file directly (path bootstrap below)
"""
import asyncio
import logging
import os
import signal
import sys

# ── Path bootstrap ────────────────────────────────────────────────────────────
# Allow running this file directly (`python src/server.py`) by ensuring the
# project root is importable so the absolute `src.*` imports below resolve.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from src.db.pool import close_pool

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("tcl-finance-billing")

# ── Task 04: Group L — Schema Introspection Tools ─────────────────────────────
from src.tools import schema as _schema  # noqa: E402

@mcp.tool()
async def list_tables() -> dict:
    """List all tables in MCP_APP schema with row counts."""
    return await _schema.list_tables()

@mcp.tool()
async def describe_table(table_name: str) -> dict:
    """Return columns and constraints for a given table."""
    return await _schema.describe_table(table_name)

@mcp.tool()
async def list_packages() -> dict:
    """List all PL/SQL packages in MCP_APP schema."""
    return await _schema.list_packages()

@mcp.tool()
async def list_package_procedures(package_name: str) -> dict:
    """List all procedures and functions in a given package."""
    return await _schema.list_package_procedures(package_name)

@mcp.tool()
async def get_procedure_signature(package_name: str, procedure_name: str) -> dict:
    """Return parameter list for a specific package procedure."""
    return await _schema.get_procedure_signature(package_name, procedure_name)

@mcp.tool()
async def list_sequences() -> dict:
    """List all sequences in MCP_APP schema."""
    return await _schema.list_sequences()

@mcp.tool()
async def list_indexes(table_name: str = "") -> dict:
    """List indexes for a table, or all indexes if no table given."""
    return await _schema.list_indexes(table_name or None)

@mcp.tool()
async def find_procedure_for_table(table_name: str) -> dict:
    """Find all package source lines that reference a given table name."""
    return await _schema.find_procedure_for_table(table_name)


async def _shutdown() -> None:
    logger.info("Shutting down — closing Oracle connection pool…")
    await close_pool()


def _register_signals() -> None:
    loop = asyncio.get_event_loop()

    def _handler(sig, frame):  # noqa: ANN001
        logger.info("Signal %s received — initiating shutdown", sig)
        loop.create_task(_shutdown())

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ── Task 07: Groups C & D — Address, Contact, Account Read Tools ──────────────
from src.tools import account as _account  # noqa: E402

@mcp.tool()
async def get_customer_addresses(customer_number: str) -> dict:
    """Return all addresses for a customer."""
    return await _account.get_customer_addresses(customer_number)

@mcp.tool()
async def get_customer_contacts(customer_number: str) -> dict:
    """Return all contacts (with phone) for a customer."""
    return await _account.get_customer_contacts(customer_number)

@mcp.tool()
async def search_contacts_by_email(email_pattern: str, limit: int = 50) -> dict:
    """Search contacts by email pattern (case-insensitive LIKE)."""
    return await _account.search_contacts_by_email(email_pattern, limit)

@mcp.tool()
async def get_accounts_by_customer(customer_number: str,
                                   status: str = "") -> dict:
    """Return accounts for a customer, optionally filtered by status."""
    return await _account.get_accounts_by_customer(
        customer_number, status or None)

@mcp.tool()
async def get_account_details(account_number: str) -> dict:
    """Return full account details via ACCOUNT_PKG.GET_ACCOUNT_DETAILS."""
    return await _account.get_account_details(account_number)

@mcp.tool()
async def get_accounts_by_currency(currency_code: str,
                                   status: str = "ACTIVE",
                                   limit: int = 50) -> dict:
    """Return accounts using a specific currency."""
    return await _account.get_accounts_by_currency(currency_code, status, limit)

@mcp.tool()
async def get_account_commissioning_info(account_number: str) -> dict:
    """Return commissioning and termination dates for an account."""
    return await _account.get_account_commissioning_info(account_number)

@mcp.tool()
async def get_accounts_by_billing_cycle(billing_cycle: str,
                                        status: str = "ACTIVE",
                                        limit: int = 50) -> dict:
    """Return accounts matching a billing cycle (e.g. MONTHLY)."""
    return await _account.get_accounts_by_billing_cycle(billing_cycle, status, limit)

@mcp.tool()
async def get_accounts_pending_termination(days_ahead: int = 30) -> dict:
    """Return accounts with termination dates within the next N days."""
    return await _account.get_accounts_pending_termination(days_ahead)


# ── Task 08: Groups E & F — Product & Billing Read Tools ─────────────────────
from src.tools import billing as _billing  # noqa: E402

@mcp.tool()
async def get_products(product_type: str = "",
                       status: str = "ACTIVE") -> dict:
    """List products, optionally filtered by type and status."""
    return await _billing.get_products(product_type or None, status)

@mcp.tool()
async def get_product_by_code(product_code: str) -> dict:
    """Return a single product by its code."""
    return await _billing.get_product_by_code(product_code)

@mcp.tool()
async def get_customer_products(customer_number: str,
                                status: str = "") -> dict:
    """Return products subscribed by a customer."""
    return await _billing.get_customer_products(customer_number, status or None)

@mcp.tool()
async def get_bills_by_account(account_number: str,
                                date_from: str = "",
                                date_to: str = "",
                                status: str = "") -> dict:
    """Return bills for an account via BILLING_PKG.GET_BILL_DETAILS."""
    return await _billing.get_bills_by_account(
        account_number, date_from or None, date_to or None, status or None)

@mcp.tool()
async def get_bill_by_invoice_number(invoice_number: str) -> dict:
    """Return a specific bill by invoice number."""
    return await _billing.get_bill_by_invoice_number(invoice_number)

@mcp.tool()
async def get_billing_summary_by_customer(customer_number: str) -> dict:
    """Return aggregated billing totals for a customer."""
    return await _billing.get_billing_summary_by_customer(customer_number)

@mcp.tool()
async def get_unpaid_bills(currency_code: str = "",
                           limit: int = 50) -> dict:
    """Return unpaid (non-PAID, non-CANCELLED) bills."""
    return await _billing.get_unpaid_bills(currency_code or None, limit)

@mcp.tool()
async def get_monthly_revenue(months: int = 12) -> dict:
    """Return monthly revenue totals for the last N months."""
    return await _billing.get_monthly_revenue(months)

@mcp.tool()
async def get_revenue_by_product_type() -> dict:
    """Return revenue broken down by product type."""
    return await _billing.get_revenue_by_product_type()

@mcp.tool()
async def get_pending_adjustments() -> dict:
    """Return pending billing adjustments via BILLING_ADJUSTMENT_PKG."""
    return await _billing.get_pending_adjustments()


# ── Task 09: Groups G, H, I — Usage Analytics & Operations Read Tools ─────────
from src.tools import usage as _usage  # noqa: E402

@mcp.tool()
async def get_events_by_account(account_number: str,
                                 date_from: str = "",
                                 date_to: str = "",
                                 limit: int = 50) -> dict:
    """Return costed events for an account via USAGE_ANALYTICS_PKG.GET_ACCOUNT_USAGE."""
    return await _usage.get_events_by_account(
        account_number, date_from or None, date_to or None, limit)

@mcp.tool()
async def get_event_summary(account_number: str,
                             date_from: str = "",
                             date_to: str = "") -> dict:
    """Return aggregated usage stats (bits, speed, count) for an account."""
    return await _usage.get_event_summary(
        account_number, date_from or None, date_to or None)

@mcp.tool()
async def get_top_usage_accounts(limit: int = 10) -> dict:
    """Return top N accounts by bandwidth via USAGE_ANALYTICS_PKG.GET_TOP_BANDWIDTH_ACCOUNTS."""
    return await _usage.get_top_usage_accounts(limit)

@mcp.tool()
async def get_events_by_source_system(source_system: str,
                                       status: str = "",
                                       limit: int = 50) -> dict:
    """Return events from a specific source system, optionally filtered by status."""
    return await _usage.get_events_by_source_system(
        source_system, status or None, limit)

@mcp.tool()
async def get_bandwidth_trend(account_number: str = "",
                               granularity: str = "DAY",
                               limit: int = 30) -> dict:
    """Return bandwidth trend grouped by DAY or MONTH."""
    return await _usage.get_bandwidth_trend(
        account_number or None, granularity, limit)

@mcp.tool()
async def get_failed_events(source_system: str = "",
                             limit: int = 50) -> dict:
    """Return events where STATUS != 'SUCCESS'."""
    return await _usage.get_failed_events(source_system or None, limit)

@mcp.tool()
async def get_usage_anomalies(threshold_mbps: float = 100.0) -> dict:
    """Return events exceeding threshold_mbps via USAGE_ANALYTICS_PKG.GET_USAGE_ANOMALIES."""
    return await _usage.get_usage_anomalies(threshold_mbps)

@mcp.tool()
async def get_load_status_today() -> dict:
    """Return today's load status per source system via LOAD_MONITOR_PKG.GET_LOAD_STATUS."""
    return await _usage.get_load_status_today()

@mcp.tool()
async def get_missing_loads(days_back: int = 7) -> dict:
    """Return source systems that have not loaded data in the past N days."""
    return await _usage.get_missing_loads(days_back)

@mcp.tool()
async def get_load_history(source_system: str, days_back: int = 30) -> dict:
    """Return load history for a source system over the last N days."""
    return await _usage.get_load_history(source_system, days_back)

@mcp.tool()
async def get_failed_load_summary(days_back: int = 7) -> dict:
    """Return summary of failed loads per source system over last N days."""
    return await _usage.get_failed_load_summary(days_back)

@mcp.tool()
async def get_open_requests(assigned_to: str = "") -> dict:
    """Return open and in-progress service requests via SERVICE_REQUEST_PKG.GET_OPEN_REQUESTS."""
    return await _usage.get_open_requests(assigned_to or None)

@mcp.tool()
async def get_requests_by_customer(customer_number: str) -> dict:
    """Return all service requests for a customer via SERVICE_REQUEST_PKG.GET_REQUESTS_BY_CUSTOMER."""
    return await _usage.get_requests_by_customer(customer_number)


# ── Task 10: Group M — Cross-Entity Power Query Tools ────────────────────────
from src.tools import power as _power  # noqa: E402

@mcp.tool()
async def search_globally(query: str, limit: int = 50) -> dict:
    """Search CUSTOMER_NAME, ACCOUNT_NUMBER, EMAIL, INVOICE_NUMBER in one call."""
    return await _power.search_globally(query, limit)

@mcp.tool()
async def get_customer_health_check(customer_number: str) -> dict:
    """Return health flags: missing_address, no_active_products, unpaid_bills, no_events_this_month."""
    return await _power.get_customer_health_check(customer_number)

@mcp.tool()
async def get_inactive_entities(entity_type: str = "ALL",
                                 limit: int = 50) -> dict:
    """Return INACTIVE customers and/or accounts (entity_type: CUSTOMER, ACCOUNT, or ALL)."""
    return await _power.get_inactive_entities(entity_type or None, limit)

@mcp.tool()
async def get_expiring_products(days_ahead: int = 30) -> dict:
    """Return active products whose END_DATE falls within the next N days."""
    return await _power.get_expiring_products(days_ahead)

@mcp.tool()
async def get_full_hierarchy(customer_number: str) -> dict:
    """Return full nested hierarchy: company → customer → accounts → products."""
    return await _power.get_full_hierarchy(customer_number)

@mcp.tool()
async def get_accounts_no_events(limit: int = 50) -> dict:
    """Return active accounts with no costed events in the current calendar month."""
    return await _power.get_accounts_no_events(limit)


# ── Task 11: Group K — Approval Workflow Engine ───────────────────────────────
from src.tools import approval as _approval  # noqa: E402

@mcp.tool()
async def get_pending_approvals(requested_by: str = "",
                                 limit: int = 50) -> dict:
    """Return all PENDING approval requests, optionally filtered by requester."""
    return await _approval.get_pending_approvals(requested_by or None, limit)

@mcp.tool()
async def get_my_pending_requests(requested_by: str,
                                   limit: int = 50) -> dict:
    """Return PENDING requests raised by a specific user."""
    return await _approval.get_my_pending_requests(requested_by, limit)

@mcp.tool()
async def get_audit_log(tool_name: str = "",
                         status: str = "",
                         limit: int = 50) -> dict:
    """Return MCP_AUDIT_LOG entries, optionally filtered by tool and status."""
    return await _approval.get_audit_log(
        tool_name or None, status or None, limit)

@mcp.tool()
async def get_audit_stats() -> dict:
    """Return per-tool call counts and success/error breakdown from MCP_AUDIT_LOG."""
    return await _approval.get_audit_stats()

@mcp.tool()
async def approve_request(request_id: int, approved_by: str) -> dict:
    """Approve a PENDING request and execute the stored DML action."""
    return await _approval.approve_request(request_id, approved_by)

@mcp.tool()
async def reject_request(request_id: int,
                          rejected_by: str,
                          reason: str = "") -> dict:
    """Reject a PENDING request — no DML is executed."""
    return await _approval.reject_request(request_id, rejected_by, reason)


# ── Task 12: All Write Tools (Groups A, B, C, D, E, F, G, I, J) ──────────────
from src.tools import writes as _writes  # noqa: E402

@mcp.tool()
async def create_provider(provider_code: str, provider_name: str,
                           service_type: str, country: str,
                           requested_by: str = "mcp_user") -> dict:
    """Create a new provider — returns PENDING approval request."""
    return await _writes.create_provider(
        provider_code, provider_name, service_type, country, requested_by)

@mcp.tool()
async def update_provider_status(provider_code: str, new_status: str,
                                  requested_by: str = "mcp_user") -> dict:
    """Update provider status — returns PENDING approval request."""
    return await _writes.update_provider_status(provider_code, new_status, requested_by)

@mcp.tool()
async def create_customer(customer_name: str, company_code: str,
                           customer_type_code: str,
                           requested_by: str = "mcp_user") -> dict:
    """Create a new customer — returns PENDING approval request."""
    return await _writes.create_customer(
        customer_name, company_code, customer_type_code, requested_by)

@mcp.tool()
async def update_customer_status(customer_number: str, new_status: str,
                                  requested_by: str = "mcp_user") -> dict:
    """Update customer status — returns PENDING approval request."""
    return await _writes.update_customer_status(customer_number, new_status, requested_by)

@mcp.tool()
async def add_customer_address(customer_number: str, address_type: str,
                                address_line1: str, city: str, country: str,
                                state: str = "", postal_code: str = "",
                                requested_by: str = "mcp_user") -> dict:
    """Add an address for a customer — returns PENDING approval request."""
    return await _writes.add_customer_address(
        customer_number, address_type, address_line1, city, country,
        state, postal_code, requested_by)

@mcp.tool()
async def add_customer_contact(customer_number: str, contact_name: str,
                                designation: str, email: str,
                                phone_number: str = "", alternate_email: str = "",
                                requested_by: str = "mcp_user") -> dict:
    """Add a contact (with optional phone/alt-email) — returns PENDING approval request."""
    return await _writes.add_customer_contact(
        customer_number, contact_name, designation, email,
        phone_number, alternate_email, requested_by)

@mcp.tool()
async def update_contact_email(contact_id: int, new_email: str,
                                requested_by: str = "mcp_user") -> dict:
    """Update a contact's email address — returns PENDING approval request."""
    return await _writes.update_contact_email(contact_id, new_email, requested_by)

@mcp.tool()
async def create_account(customer_number: str, account_name: str,
                          currency_code: str,
                          requested_by: str = "mcp_user") -> dict:
    """Create a new account (MONTHLY billing cycle) — returns PENDING approval request."""
    return await _writes.create_account(
        customer_number, account_name, currency_code, requested_by)

@mcp.tool()
async def update_account_status(account_number: str, new_status: str,
                                 requested_by: str = "mcp_user") -> dict:
    """Update account status — returns PENDING approval request."""
    return await _writes.update_account_status(account_number, new_status, requested_by)

@mcp.tool()
async def set_account_billable(account_number: str, billable_flag: str,
                                requested_by: str = "mcp_user") -> dict:
    """Set ACCOUNT_DETAILS.BILLABLE_FLAG to 'Y' or 'N' — returns PENDING approval request."""
    return await _writes.set_account_billable(account_number, billable_flag, requested_by)

@mcp.tool()
async def update_account_currency(account_number: str, currency_code: str,
                                  requested_by: str = "mcp_user") -> dict:
    """Change an account's billing currency — returns PENDING approval request,
    or NO_CHANGE if it already uses that currency."""
    return await _writes.update_account_currency(account_number, currency_code, requested_by)

@mcp.tool()
async def assign_product_to_account(customer_number: str, account_number: str,
                                     product_code: str,
                                     start_date: str = "", end_date: str = "",
                                     requested_by: str = "mcp_user") -> dict:
    """Assign a product to an account — returns PENDING approval request."""
    return await _writes.assign_product_to_account(
        customer_number, account_number, product_code, start_date, end_date, requested_by)

@mcp.tool()
async def terminate_customer_product(customer_number: str, product_code: str,
                                      end_date: str = "",
                                      requested_by: str = "mcp_user") -> dict:
    """Terminate an active product assignment — returns PENDING approval request."""
    return await _writes.terminate_customer_product(
        customer_number, product_code, end_date, requested_by)

@mcp.tool()
async def create_bill(account_number: str, bill_amount: float,
                       tax_amount: float, currency_code: str,
                       requested_by: str = "mcp_user") -> dict:
    """Generate a bill — returns PENDING approval request.
    After approval, dml_result.post_query_result contains INVOICE_NUMBER."""
    return await _writes.create_bill(
        account_number, bill_amount, tax_amount, currency_code, requested_by)

@mcp.tool()
async def update_bill_status(invoice_number: str, new_status: str,
                              requested_by: str = "mcp_user") -> dict:
    """Update a bill's status (e.g., PAID) — returns PENDING approval request."""
    return await _writes.update_bill_status(invoice_number, new_status, requested_by)

@mcp.tool()
async def create_billing_adjustment(invoice_number: str, account_number: str,
                                     adjustment_type: str, adjustment_amount: float,
                                     reason: str,
                                     requested_by: str = "mcp_user") -> dict:
    """Create a billing adjustment — returns PENDING approval request."""
    return await _writes.create_billing_adjustment(
        invoice_number, account_number, adjustment_type,
        adjustment_amount, reason, requested_by)

@mcp.tool()
async def ingest_costed_event(account_number: str, event_dtm: str,
                               in_bits: int = 0, out_bits: int = 0,
                               speed_mbps: float = 0.0, bandwidth_mbps: float = 0.0,
                               event_type: str = "DATA_USAGE",
                               source_system: str = "USAGE_COLLECTOR",
                               requested_by: str = "mcp_user") -> dict:
    """Ingest a costed event — returns PENDING approval request."""
    return await _writes.ingest_costed_event(
        account_number, event_dtm, in_bits, out_bits,
        speed_mbps, bandwidth_mbps, event_type, source_system, requested_by)

@mcp.tool()
async def create_service_request(customer_number: str, request_type: str,
                                  priority: str, description: str,
                                  raised_by: str, account_number: str = "",
                                  requested_by: str = "mcp_user") -> dict:
    """Create a service request — returns PENDING approval request."""
    return await _writes.create_service_request(
        customer_number, request_type, priority, description,
        raised_by, account_number, requested_by)

@mcp.tool()
async def assign_service_request(request_id: int, assigned_to: str,
                                  requested_by: str = "mcp_user") -> dict:
    """Assign a service request to a user — returns PENDING approval request."""
    return await _writes.assign_service_request(request_id, assigned_to, requested_by)

@mcp.tool()
async def resolve_service_request(request_id: int, resolution_notes: str,
                                   resolved_by: str,
                                   requested_by: str = "mcp_user") -> dict:
    """Resolve a service request — returns PENDING approval request."""
    return await _writes.resolve_service_request(
        request_id, resolution_notes, resolved_by, requested_by)

@mcp.tool()
async def add_customer_note(customer_number: str, note_type: str,
                             note_text: str, created_by: str,
                             requested_by: str = "mcp_user") -> dict:
    """Add a note to a customer record — returns PENDING approval request."""
    return await _writes.add_customer_note(
        customer_number, note_type, note_text, created_by, requested_by)

@mcp.tool()
async def create_currency(currency_code: str, currency_name: str,
                           requested_by: str = "mcp_user") -> dict:
    """Create a new currency — returns PENDING approval request.
    Dispatching a duplicate code returns ORA-00001."""
    return await _writes.create_currency(currency_code, currency_name, requested_by)

@mcp.tool()
async def delete_customer_note(note_id: int,
                               requested_by: str = "mcp_user") -> dict:
    """Delete a customer note — returns PENDING approval request."""
    return await _writes.delete_customer_note(note_id, requested_by)

@mcp.tool()
async def delete_customer_address(address_id: int,
                                  requested_by: str = "mcp_user") -> dict:
    """Delete a customer address — returns PENDING approval request."""
    return await _writes.delete_customer_address(address_id, requested_by)

@mcp.tool()
async def delete_customer_contact(contact_id: int,
                                  requested_by: str = "mcp_user") -> dict:
    """Delete a customer contact and its contact details — returns PENDING approval request."""
    return await _writes.delete_customer_contact(contact_id, requested_by)

@mcp.tool()
async def delete_costed_event(event_id: int,
                              requested_by: str = "mcp_user") -> dict:
    """Delete a costed usage event — returns PENDING approval request."""
    return await _writes.delete_costed_event(event_id, requested_by)


# ── Group N — DBA / Database-Administration Tools ─────────────────────────────
from src.tools import dba as _dba  # noqa: E402

@mcp.tool()
async def get_database_health() -> dict:
    """One-shot DB health snapshot: version, invalid objects, size, stale stats."""
    return await _dba.get_database_health()

@mcp.tool()
async def get_active_sessions(limit: int = 20) -> dict:
    """List current user sessions (needs V$ access; degrades with a clear message)."""
    return await _dba.get_active_sessions(limit)

@mcp.tool()
async def get_blocking_sessions() -> dict:
    """Find blocking locks / lock contention / deadlock risk (needs V$ access)."""
    return await _dba.get_blocking_sessions()

@mcp.tool()
async def get_slow_queries(limit: int = 10) -> dict:
    """Top SQL by average elapsed time — query-optimization candidates (needs V$)."""
    return await _dba.get_slow_queries(limit)

@mcp.tool()
async def get_wait_events(limit: int = 15) -> dict:
    """Top database wait events by time waited (needs V$ access)."""
    return await _dba.get_wait_events(limit)

@mcp.tool()
async def get_tablespace_usage() -> dict:
    """Space usage per tablespace (falls back to schema segment roll-up)."""
    return await _dba.get_tablespace_usage()

@mcp.tool()
async def get_segment_sizes(limit: int = 20) -> dict:
    """Largest segments (tables/indexes) in the schema."""
    return await _dba.get_segment_sizes(limit)

@mcp.tool()
async def get_invalid_objects() -> dict:
    """List INVALID schema objects that need recompilation."""
    return await _dba.get_invalid_objects()

@mcp.tool()
async def get_unused_indexes() -> dict:
    """Secondary (non-constraint) indexes to review for removal."""
    return await _dba.get_unused_indexes()

@mcp.tool()
async def get_redundant_indexes() -> dict:
    """Indexes whose columns prefix another index on the same table (redundant)."""
    return await _dba.get_redundant_indexes()

@mcp.tool()
async def get_table_stats_status() -> dict:
    """Tables with missing or stale optimizer statistics (gather-stats candidates)."""
    return await _dba.get_table_stats_status()

@mcp.tool()
async def get_long_operations() -> dict:
    """Long-running operations currently in progress (perceived slowdown)."""
    return await _dba.get_long_operations()

@mcp.tool()
async def drop_index(index_name: str, requested_by: str = "mcp_user") -> dict:
    """Drop a non-constraint index — returns PENDING approval request."""
    return await _dba.drop_index(index_name, requested_by)

@mcp.tool()
async def rebuild_index(index_name: str, requested_by: str = "mcp_user") -> dict:
    """Rebuild/defragment an index — returns PENDING approval request."""
    return await _dba.rebuild_index(index_name, requested_by)

@mcp.tool()
async def gather_table_stats(table_name: str, requested_by: str = "mcp_user") -> dict:
    """Gather/refresh optimizer statistics for a table — returns PENDING approval request."""
    return await _dba.gather_table_stats(table_name, requested_by)

@mcp.tool()
async def recompile_object(object_name: str, requested_by: str = "mcp_user") -> dict:
    """Recompile an INVALID object — returns PENDING approval request."""
    return await _dba.recompile_object(object_name, requested_by)


# ── Task 14: schema_agent ─────────────────────────────────────────────────────
from src.agents import schema_agent as _schema_agent_mod  # noqa: E402

@mcp.tool()
async def schema_agent(question: str) -> dict:
    """Answer natural language questions about the MCP_APP Oracle schema using GPT-4o.
    Routes to list_packages, describe_table, get_procedure_signature, etc."""
    return await _schema_agent_mod.run(question)


# ── Task 05: Groups A & J — Reference & Lookup Read Tools ────────────────────
from src.tools import reference as _reference  # noqa: E402

@mcp.tool()
async def get_providers(status: str = "ACTIVE") -> dict:
    """List providers, filtered by status ('ACTIVE', 'INACTIVE', or 'ALL')."""
    return await _reference.get_providers(status)

@mcp.tool()
async def get_provider_details(provider_code: str) -> dict:
    """Return a single provider by its code."""
    return await _reference.get_provider_details(provider_code)

@mcp.tool()
async def get_invoicing_companies(country: str = "", status: str = "ACTIVE") -> dict:
    """List invoicing companies, optionally filtered by country and status."""
    return await _reference.get_invoicing_companies(country or None, status)

@mcp.tool()
async def get_currencies() -> dict:
    """List all supported currencies."""
    return await _reference.get_currencies()

@mcp.tool()
async def get_currency_by_code(currency_code: str) -> dict:
    """Return a single currency by its code (e.g. USD)."""
    return await _reference.get_currency_by_code(currency_code)

@mcp.tool()
async def get_customer_types() -> dict:
    """List all customer types (Enterprise, SMB, Government, etc.)."""
    return await _reference.get_customer_types()


# ── Task 06: Group B — Customer Read Tools ────────────────────────────────────
from src.tools import customer as _customer  # noqa: E402

@mcp.tool()
async def search_customers(name: str = "", status: str = "",
                           limit: int = 50, offset: int = 0) -> dict:
    """Search customers by name (case-insensitive LIKE), with pagination."""
    return await _customer.search_customers(name or None, status or None, limit, offset)

@mcp.tool()
async def get_customer_by_number(customer_number: str) -> dict:
    """Return a single customer joined with type and invoicing company."""
    return await _customer.get_customer_by_number(customer_number)

@mcp.tool()
async def get_customer_360(customer_number: str) -> dict:
    """Return a full customer profile: addresses, contacts, accounts, products, latest bill."""
    return await _customer.get_customer_360(customer_number)

@mcp.tool()
async def get_customers_by_company(company_code: str, status: str = "ACTIVE",
                                   limit: int = 50) -> dict:
    """Return customers belonging to an invoicing company."""
    return await _customer.get_customers_by_company(company_code, status, limit)

@mcp.tool()
async def get_customer_summary_stats() -> dict:
    """Return customer totals: total, active, inactive, and breakdown by type."""
    return await _customer.get_customer_summary_stats()


# ── Tasks 15-23: Higher-level agents exposed as natural-language MCP tools ────
from src.agents import (  # noqa: E402
    intent_router as _intent_router,
    read_master_agent as _read_master,
    write_master_agent as _write_master,
    customer_read_agent as _customer_read_agent,
    billing_read_agent as _billing_read_agent,
    usage_read_agent as _usage_read_agent,
    operations_read_agent as _operations_read_agent,
    rca_agent as _rca_agent,
    insight_agent as _insight_agent,
    dml_agent as _dml_agent,
    approval_agent as _approval_agent,
    onboarding_agent as _onboarding_agent,
    billing_run_agent as _billing_run_agent,
    adjustment_agent as _adjustment_agent,
    dba_agent as _dba_agent,
)

@mcp.tool()
async def ask(question: str) -> dict:
    """PRIMARY ENTRY POINT. Ask anything in plain English about TCL Finance &
    Billing. The intent router classifies it as READ or WRITE and routes to the
    correct master agent and sub-agent. Use this for natural-language questions."""
    return await _intent_router.run(question)

@mcp.tool()
async def read_master_agent(question: str) -> dict:
    """Route a read/lookup/analysis question to the correct read sub-agent."""
    return await _read_master.run(question)

@mcp.tool()
async def query_data(question: str) -> dict:
    """Answer ANY read question about the data by generating and running a safe,
    read-only SQL SELECT against MCP_APP (capped, audited). Use for specific record
    lookups, lists, ids, counts, and ad-hoc filters."""
    from src.agents import sql_read_agent as _sql_agent
    return await _sql_agent.run(question)

@mcp.tool()
async def write_master_agent(question: str) -> dict:
    """Route a write/DML request to the correct write sub-agent (approval-gated)."""
    return await _write_master.run(question)

@mcp.tool()
async def customer_read_agent(question: str) -> dict:
    """Answer customer-centric questions (lookups, contacts, addresses, products)."""
    return await _customer_read_agent.run(question)

@mcp.tool()
async def billing_read_agent(question: str) -> dict:
    """Answer billing questions (invoices, revenue, unpaid bills, adjustments)."""
    return await _billing_read_agent.run(question)

@mcp.tool()
async def usage_read_agent(question: str) -> dict:
    """Answer usage/analytics questions (events, bandwidth, anomalies, failures)."""
    return await _usage_read_agent.run(question)

@mcp.tool()
async def operations_read_agent(question: str) -> dict:
    """Answer operations questions (load status, service requests, inactive entities)."""
    return await _operations_read_agent.run(question)

@mcp.tool()
async def rca_agent(customer_number: str) -> dict:
    """Run a full automated root-cause analysis for a customer (chains 7 tools + GPT-4o)."""
    return await _rca_agent.run(customer_number)

@mcp.tool()
async def insight_agent(question: str) -> dict:
    """Generate an executive financial narrative (revenue, products, payments + GPT-4o)."""
    return await _insight_agent.run(question)

@mcp.tool()
async def dml_agent(question: str) -> dict:
    """Handle a single natural-language write op via the approval workflow."""
    return await _dml_agent.run(question)

@mcp.tool()
async def approval_agent(question: str) -> dict:
    """Manage the approval queue in natural language (list / approve / reject)."""
    return await _approval_agent.run(question)

@mcp.tool()
async def onboarding_agent(customer_name: str, company_code: str,
                           customer_type_code: str, address_type: str,
                           address_line1: str, city: str, country: str,
                           contact_name: str, designation: str, email: str,
                           account_name: str, currency_code: str,
                           product_code: str, phone_number: str = "",
                           start_date: str = "",
                           requested_by: str = "mcp_user") -> dict:
    """Full customer onboarding — stages 5 approval requests (customer → address →
    contact → account → product) in dependency order. Takes structured fields."""
    return await _onboarding_agent.run({
        "customer_name": customer_name, "company_code": company_code,
        "customer_type_code": customer_type_code, "address_type": address_type,
        "address_line1": address_line1, "city": city, "country": country,
        "contact_name": contact_name, "designation": designation, "email": email,
        "account_name": account_name, "currency_code": currency_code,
        "product_code": product_code, "phone_number": phone_number,
        "start_date": start_date, "requested_by": requested_by,
    })

@mcp.tool()
async def billing_run_agent(billing_month: str, requested_by: str = "mcp_user") -> dict:
    """Execute the monthly billing run for all eligible MONTHLY-cycle accounts."""
    return await _billing_run_agent.run(billing_month, requested_by)

@mcp.tool()
async def adjustment_agent(question: str) -> dict:
    """Create a billing adjustment (CREDIT / DISPUTE / WAIVER) via the approval workflow."""
    return await _adjustment_agent.run(question)

@mcp.tool()
async def dba_agent(question: str) -> dict:
    """Database-administration agent in plain English: DB health, slow queries,
    deadlocks/blocking, wait events, space usage, invalid objects, unused/redundant
    indexes, stale stats, long operations (reads), and index/stats/recompile
    maintenance (approval-gated writes)."""
    return await _dba_agent.run(question)


if __name__ == "__main__":
    _register_signals()
    mcp.run()
