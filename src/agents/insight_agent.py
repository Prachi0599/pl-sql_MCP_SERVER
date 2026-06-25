"""insight_agent — Executive insight reports via GPT-4o narrative synthesis.

Pattern B: 4 hardcoded tool calls (always the same), then GPT-4o for narrative.

Exposes a single public coroutine:
    run(question: str) -> dict

Flow:
  1. get_monthly_revenue(months=12)
  2. get_revenue_by_product_type()
  3. get_top_usage_accounts(limit=10)
  4. get_unpaid_bills()
  → GPT-4o chat completion  — narrative summary
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import AsyncOpenAI

from src.tools import billing as _billing
from src.tools import usage as _usage
from src.utils.audit import log_audit

_AGENT = "insight_agent"
_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_INSIGHT_SYSTEM = (
    "You are a senior finance analyst producing executive summaries for TCL, "
    "a telecom company. You are given revenue, product, usage, and outstanding "
    "payment data. Produce a concise narrative summary tailored to the user's question. "
    "Respond ONLY with a valid JSON object with exactly one key: "
    "'narrative' (a string, 3-5 sentences suitable for a business executive). "
    "Do not include any text outside the JSON object."
)

# Quarter → zero-padded month numbers
_QUARTER_MONTHS: dict[str, list[str]] = {
    "q1": ["01", "02", "03"],
    "q2": ["04", "05", "06"],
    "q3": ["07", "08", "09"],
    "q4": ["10", "11", "12"],
}

_MONTH_NAMES: dict[str, str] = {
    "january": "01", "february": "02", "march": "03",
    "april":   "04", "may":      "05", "june":   "06",
    "july":    "07", "august":   "08", "september": "09",
    "october": "10", "november": "11", "december":  "12",
}


def _detect_period(question: str) -> tuple[str, list[str] | None, str | None]:
    """
    Parse the question for a time period reference.

    Returns:
        (period_label, month_nums_filter, year_filter)
        month_nums_filter: list of zero-padded month strings to keep, or None = keep all
        year_filter: 4-digit year string to keep, or None = all years
    """
    q = question.lower()

    year_match = re.search(r"\b(20\d{2})\b", q)
    year = year_match.group(1) if year_match else None

    # Quarter
    for q_key, months in _QUARTER_MONTHS.items():
        if q_key in q:
            label = q_key.upper()
            if year:
                label = f"{label} {year}"
            return label, months, year

    # Named month
    for name, num in _MONTH_NAMES.items():
        if name in q:
            label = name.capitalize()
            if year:
                label = f"{label} {year}"
            return label, [num], year

    # "last N months"
    m = re.search(r"last\s+(\d+)\s+months?", q)
    if m:
        n = int(m.group(1))
        return f"last {n} months", None, None

    return "last 12 months", None, None


def _filter_revenue(
    rows: list[dict],
    month_nums: list[str] | None,
    year: str | None,
) -> list[dict]:
    """Filter monthly revenue rows by detected period."""
    if not rows:
        return rows
    result = rows
    if year:
        result = [r for r in result if str(r.get("month", "")).startswith(year)]
    if month_nums:
        result = [
            r for r in result
            if any(str(r.get("month", "")).endswith(f"-{m}") for m in month_nums)
        ]
    return result


async def run(question: str) -> dict:
    """
    Produce an executive insight report using GPT-4o narrative synthesis.

    Returns:
        {
          "success": True,
          "question": str,
          "period": str,
          "revenue_total": float,
          "product_breakdown": list[dict],
          "top_accounts": list[dict],
          "outstanding": list[dict],
          "narrative": str,
        }
    """
    period_label, month_nums, year_filter = _detect_period(question)

    # ── Step 1: monthly revenue ───────────────────────────────────────────────
    revenue_raw: list[dict] = []
    try:
        r1 = await _billing.get_monthly_revenue(months=12)
        if r1.get("success"):
            revenue_raw = r1.get("data") or []
    except Exception:
        pass

    revenue_filtered = _filter_revenue(revenue_raw, month_nums, year_filter)
    revenue_total: float = sum(
        float(r.get("total_revenue") or 0) for r in revenue_filtered
    )

    # ── Step 2: revenue by product type ──────────────────────────────────────
    product_breakdown: list[dict] = []
    try:
        r2 = await _billing.get_revenue_by_product_type()
        if r2.get("success"):
            product_breakdown = r2.get("data") or []
    except Exception:
        pass

    # ── Step 3: top usage accounts ────────────────────────────────────────────
    top_accounts: list[dict] = []
    try:
        r3 = await _usage.get_top_usage_accounts(limit=10)
        if r3.get("success"):
            top_accounts = r3.get("data") or []
    except Exception:
        pass

    # ── Step 4: unpaid bills ──────────────────────────────────────────────────
    outstanding: list[dict] = []
    try:
        r4 = await _billing.get_unpaid_bills()
        if r4.get("success"):
            outstanding = r4.get("data") or []
    except Exception:
        pass

    # ── GPT-4o narrative ──────────────────────────────────────────────────────
    narrative = "narrative unavailable"

    payload_for_gpt: dict[str, Any] = {
        "question": question,
        "period": period_label,
        "monthly_revenue": revenue_filtered,
        "revenue_total": revenue_total,
        "product_breakdown": product_breakdown,
        "top_accounts_by_usage": top_accounts[:10],
        "outstanding_bills_sample": outstanding[:20],
        "outstanding_total": sum(float(b.get("total_amount") or 0) for b in outstanding),
    }

    try:
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _INSIGHT_SYSTEM},
                {"role": "user",   "content": json.dumps(payload_for_gpt, default=str)},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        narrative = parsed.get("narrative", narrative)
    except Exception:
        pass  # GPT-4o failure → keep "narrative unavailable"; success=True

    await log_audit(
        _AGENT, "", question[:100], "READ",
        {
            "question": question[:100],
            "period": period_label,
            "revenue_total": revenue_total,
        },
        "SUCCESS",
    )

    return {
        "success": True,
        "question": question,
        "period": period_label,
        "revenue_total": revenue_total,
        "product_breakdown": product_breakdown,
        "top_accounts": top_accounts,
        "outstanding": outstanding,
        "narrative": narrative,
    }
