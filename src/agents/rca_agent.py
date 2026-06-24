"""rca_agent — Automated root-cause analysis for a customer.

Pattern B: 7 hardcoded sequential tool calls, then GPT-4o synthesis.

Exposes a single public coroutine:
    run(customer_number: str) -> dict

Flow:
  1. get_customer_360          — full profile + accounts
  2. get_accounts_by_customer  — account list (for structured iteration)
  3. get_bills_by_account      — per account, via asyncio.gather
  4. get_event_summary         — per account, via asyncio.gather
  5. get_failed_events         — global failed events
  6. get_load_status_today     — pipeline health
  7. get_customer_health_check — health flags
  → GPT-4o chat completion     — RCA narrative + recommended actions
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from openai import AsyncOpenAI

from src.tools import account as _account
from src.tools import billing as _billing
from src.tools import customer as _customer
from src.tools import power as _power
from src.tools import usage as _usage
from src.utils.audit import log_audit

_AGENT = "rca_agent"
_MODEL = "gpt-4o"

_TOOLS_USED = [
    "get_customer_360",
    "get_accounts_by_customer",
    "get_bills_by_account",
    "get_event_summary",
    "get_failed_events",
    "get_load_status_today",
    "get_customer_health_check",
]

_RCA_SYSTEM = (
    "You are a root-cause analysis engine for a telecom Finance & Billing system. "
    "You are given structured data about a customer: their profile, billing records, "
    "usage event summaries, failed data pipeline events, pipeline load status, and "
    "health check flags. "
    "Identify the root cause of any billing or data issues and provide recommended actions. "
    "Respond ONLY with a valid JSON object with exactly two keys: "
    "'rca_summary' (a concise string explanation of the root cause) and "
    "'recommended_actions' (a list of short, actionable strings). "
    "Do not include any text outside the JSON object."
)


def _extract_billing_issues(bills_result: dict) -> list[dict]:
    """Return only UNPAID or OVERDUE bills from a get_bills_by_account result."""
    if not bills_result.get("success"):
        return []
    return [
        b for b in (bills_result.get("data") or [])
        if str(b.get("bill_status", "")).upper() in ("UNPAID", "OVERDUE")
    ]


def _extract_event_anomaly(account_number: str, summary_result: dict) -> dict | None:
    """Return an anomaly entry if the account has 0 events or unusually high speed."""
    if not summary_result.get("success"):
        return None
    data = summary_result.get("data") or {}
    event_count = data.get("event_count") or 0
    avg_speed = float(data.get("avg_speed_mbps") or 0)
    if event_count == 0 or avg_speed > 100:
        return {
            "account_number": account_number,
            "event_count": event_count,
            "avg_speed_mbps": avg_speed,
            "flag": "no_events" if event_count == 0 else "high_speed",
        }
    return None


async def run(customer_number: str) -> dict:
    """
    Run a full root-cause analysis for the given customer.

    Returns:
        {
          "success": True,
          "customer_number": str,
          "customer_profile": dict,
          "billing_issues": list[dict],
          "event_anomalies": list[dict],
          "health_flags": dict,
          "rca_summary": str,
          "recommended_actions": list[str],
        }
    """
    # ── Step 1: customer 360 ──────────────────────────────────────────────────
    profile_result = await _customer.get_customer_360(customer_number)
    if not profile_result.get("success") or profile_result.get("data") is None:
        await log_audit(_AGENT, "", customer_number, "READ",
                        {"customer_number": customer_number,
                         "tools_used": ["get_customer_360"]},
                        "ERROR", "Customer not found")
        return {
            "success": False,
            "error_code": "NOT_FOUND",
            "customer_number": customer_number,
            "message": f"Customer '{customer_number}' not found",
        }

    customer_profile: dict[str, Any] = profile_result["data"]

    # ── Step 2: accounts ──────────────────────────────────────────────────────
    accounts_result = await _account.get_accounts_by_customer(customer_number)
    accounts: list[dict] = []
    if accounts_result.get("success"):
        accounts = accounts_result.get("data") or []

    account_numbers = [a["account_number"] for a in accounts if a.get("account_number")]

    # ── Steps 3 & 4: per-account bills + event summaries (parallel) ───────────
    billing_issues: list[dict] = []
    event_anomalies: list[dict] = []

    if account_numbers:
        bills_tasks = [_billing.get_bills_by_account(acc) for acc in account_numbers]
        events_tasks = [_usage.get_event_summary(acc) for acc in account_numbers]

        bills_results, events_results = await asyncio.gather(
            asyncio.gather(*bills_tasks),
            asyncio.gather(*events_tasks),
        )

        for acc_num, b_res in zip(account_numbers, bills_results):
            billing_issues.extend(_extract_billing_issues(b_res))

        for acc_num, e_res in zip(account_numbers, events_results):
            anomaly = _extract_event_anomaly(acc_num, e_res)
            if anomaly:
                event_anomalies.append(anomaly)

    # ── Step 5: global failed events ─────────────────────────────────────────
    failed_events_result = await _usage.get_failed_events()
    failed_events: list[dict] = []
    if failed_events_result.get("success"):
        failed_events = failed_events_result.get("data") or []

    # ── Step 6: load status today ─────────────────────────────────────────────
    load_status_result = await _usage.get_load_status_today()
    load_status: list[dict] = []
    if load_status_result.get("success"):
        load_status = load_status_result.get("data") or []

    # ── Step 7: health check ──────────────────────────────────────────────────
    health_result = await _power.get_customer_health_check(customer_number)
    health_flags: dict = {}
    if health_result.get("success"):
        health_flags = health_result.get("data") or {}

    # ── GPT-4o RCA synthesis ──────────────────────────────────────────────────
    rca_summary = "AI summary unavailable"
    recommended_actions: list[str] = []

    payload_for_gpt = {
        "customer_number": customer_number,
        "customer_profile": customer_profile,
        "billing_issues": billing_issues,
        "event_anomalies": event_anomalies,
        "failed_events_sample": failed_events[:10],
        "load_status_today": load_status,
        "health_flags": health_flags,
    }

    try:
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _RCA_SYSTEM},
                {"role": "user",   "content": json.dumps(payload_for_gpt, default=str)},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        rca_summary = parsed.get("rca_summary", rca_summary)
        recommended_actions = parsed.get("recommended_actions", [])
    except Exception:
        pass  # GPT-4o failure → keep defaults; success=True (data collected)

    await log_audit(
        _AGENT, "", customer_number[:100], "READ",
        {
            "customer_number": customer_number,
            "tools_used": _TOOLS_USED,
            "billing_issues_count": len(billing_issues),
            "event_anomalies_count": len(event_anomalies),
        },
        "SUCCESS",
    )

    return {
        "success": True,
        "customer_number": customer_number,
        "customer_profile": customer_profile,
        "billing_issues": billing_issues,
        "event_anomalies": event_anomalies,
        "health_flags": health_flags,
        "rca_summary": rca_summary,
        "recommended_actions": recommended_actions,
    }
