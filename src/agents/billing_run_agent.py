"""billing_run_agent — Monthly billing run for all MONTHLY-cycle accounts.

Pattern B: hardcoded sequential/parallel tool calls, no GPT-4o.

Exposes a single public coroutine:
    run(billing_month: str, requested_by: str = "mcp_user") -> dict

Flow:
  1. get_accounts_by_billing_cycle("MONTHLY")   — account list
  2. get_usage_anomalies(threshold_mbps=100)    — anomaly set (1 global call)
  3. asyncio.gather: get_account_commissioning_info + get_event_summary per account
  4. Eligibility per account:
       - billable_flag != "Y"  → skipped_no_flag
       - event_count == 0      → skipped_no_events
       - in anomaly set        → flagged_anomalies (still billed)
  5. create_bill for each eligible account → approval_ids[]
"""
from __future__ import annotations

import asyncio

from src.tools import account as _account
from src.tools import usage as _usage
from src.tools import writes as _writes
from src.utils.audit import log_audit

# Each per-account task holds one query connection then acquires a second for
# audit before releasing the first.  With pool max=10 and conftest holding 1,
# 9 slots are free.  Capping concurrency at 4 keeps peak demand at 4×2=8 < 9.
_CONCURRENCY = 4

_AGENT = "billing_run_agent"

_DEFAULT_BILL_AMOUNT = 1000.0
_DEFAULT_TAX_AMOUNT  = 100.0


async def run(billing_month: str, requested_by: str = "mcp_user") -> dict:
    """
    Execute a monthly billing run.

    Args:
        billing_month: Target billing month string (e.g. "2026-06"), stored as
                       a label only — bill amounts are fixed defaults for this run.
        requested_by: Username initiating the run.

    Returns:
        {
          "success": True,
          "billing_month": str,
          "total": int,                  # total accounts processed
          "queued": int,                 # bills queued (PENDING approval)
          "skipped_no_flag": [str, ...], # account_numbers skipped (not billable)
          "skipped_no_events": [str, ...],
          "flagged_anomalies": [str, ...],
          "approval_ids": [int, ...],
        }
    """
    skipped_no_flag:   list[str] = []
    skipped_no_events: list[str] = []
    flagged_anomalies: list[str] = []
    approval_ids:      list[int] = []

    # ── Step 1: fetch all MONTHLY accounts ───────────────────────────────────
    acc_result = await _account.get_accounts_by_billing_cycle("MONTHLY")
    accounts: list[dict] = []
    if acc_result.get("success"):
        accounts = acc_result.get("data") or []

    if not accounts:
        await log_audit(
            _AGENT, "", billing_month, "WRITE",
            {"billing_month": billing_month, "queued": 0, "total": 0},
            "SUCCESS",
        )
        return _result(billing_month, 0, 0,
                       skipped_no_flag, skipped_no_events,
                       flagged_anomalies, approval_ids)

    # ── Step 2: global anomaly set ────────────────────────────────────────────
    anomaly_result = await _usage.get_usage_anomalies(threshold_mbps=100)
    anomaly_set: set[str] = set()
    if anomaly_result.get("success"):
        anomaly_set = {
            str(r.get("account_number", ""))
            for r in (anomaly_result.get("data") or [])
            if r.get("account_number")
        }

    # ── Step 3: per-account commissioning info + event summary in parallel ────
    account_numbers = [a["account_number"] for a in accounts]

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(coro):
        async with sem:
            return await coro

    all_tasks = (
        [_bounded(_account.get_account_commissioning_info(n)) for n in account_numbers]
        + [_bounded(_usage.get_event_summary(n)) for n in account_numbers]
    )
    all_results = await asyncio.gather(*all_tasks)
    comm_results  = list(all_results[:len(account_numbers)])
    event_results = list(all_results[len(account_numbers):])

    # ── Step 4 + 5: eligibility check and bill creation ───────────────────────
    for acc, comm_res, evt_res in zip(accounts, comm_results, event_results):
        acc_num = acc["account_number"]

        comm_data    = comm_res.get("data") or {}
        billable_flag = comm_data.get("billable_flag", "N") if isinstance(comm_data, dict) else "N"

        event_data  = evt_res.get("data") or {}
        event_count = int(event_data.get("event_count") or 0) if isinstance(event_data, dict) else 0

        if billable_flag != "Y":
            skipped_no_flag.append(acc_num)
            continue

        if event_count == 0:
            skipped_no_events.append(acc_num)
            continue

        if acc_num in anomaly_set:
            flagged_anomalies.append(acc_num)
            # still billed — fall through to create_bill

        currency_code = acc.get("currency_code") or "USD"
        bill_res = await _writes.create_bill(
            account_number=acc_num,
            bill_amount=_DEFAULT_BILL_AMOUNT,
            tax_amount=_DEFAULT_TAX_AMOUNT,
            currency_code=currency_code,
            requested_by=requested_by,
        )
        if bill_res.get("success"):
            req_id = bill_res.get("request_id")
            if req_id is not None:
                approval_ids.append(req_id)

    queued = len(approval_ids)
    total  = len(accounts)

    await log_audit(
        _AGENT, "", billing_month, "WRITE",
        {
            "billing_month": billing_month,
            "total": total,
            "queued": queued,
            "skipped_no_flag": len(skipped_no_flag),
            "skipped_no_events": len(skipped_no_events),
            "flagged_anomalies": len(flagged_anomalies),
        },
        "SUCCESS",
    )

    return _result(billing_month, total, queued,
                   skipped_no_flag, skipped_no_events,
                   flagged_anomalies, approval_ids)


def _result(billing_month: str, total: int, queued: int,
            skipped_no_flag: list, skipped_no_events: list,
            flagged_anomalies: list, approval_ids: list) -> dict:
    return {
        "success": True,
        "billing_month": billing_month,
        "total": total,
        "queued": queued,
        "skipped_no_flag": skipped_no_flag,
        "skipped_no_events": skipped_no_events,
        "flagged_anomalies": flagged_anomalies,
        "approval_ids": approval_ids,
    }
