"""
Validation agent: reviews today's Excel entries and flags anomalies.

Runs two passes:
  1. Rule-based checks (fast, deterministic) — duplicates, amount limits, missing fields
  2. Claude-based checks (catches nuanced issues) — suspicious reasons, policy violations
"""

import json
from datetime import date, timedelta
from typing import Optional


from loguru import logger

from config.settings import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    MAX_SINGLE_WITHDRAWAL, REQUIRE_REASON, FLAG_DUPLICATE_DAYS,
)
from utils.excel_manager import get_today_entries, update_validation_status


import os
from google import genai
from google.genai import types

import ollama
OLLAMA_MODEL = "llama3.2"


VALIDATION_SYSTEM = """You are a Provident Fund ledger auditor for a Pakistani company.
Review the provided list of PF withdrawal entries for today and identify any issues
not already caught by the rule-based checks.

Look for:
- Reasons that are too vague or generic (e.g. "personal need", "urgent requirement")
- Amounts that seem disproportionate to the employee's grade or balance
- Patterns suggesting the same request was submitted twice in slightly different wording
- Missing critical information that makes the request non-compliant
- Anything else an experienced bookkeeper would flag

Respond ONLY with a JSON array (no markdown):
[
  {
    "row": <Excel row number>,
    "employee_index": "EMP-XXXX",
    "severity": "warning | error",
    "code": "SHORT_CODE",
    "description": "Clear 1-sentence explanation for the bookkeeper"
  }
]
Return [] if everything looks fine."""


# ── Rule-based checks ─────────────────────────────────────────────────────────

def _check_missing_fields(entry: dict, row: int) -> list[dict]:
    issues = []
    if not entry.get("Employee Index"):
        issues.append(_issue(row, entry, "error", "MISSING_EMP_ID",
                             "Employee index is missing — cannot identify the requester."))
    if not entry.get("Amount Requested (PKR)"):
        issues.append(_issue(row, entry, "error", "MISSING_AMOUNT",
                             "No withdrawal amount specified."))
    if REQUIRE_REASON and not entry.get("Reason"):
        issues.append(_issue(row, entry, "warning", "MISSING_REASON",
                             "No reason provided for the PF withdrawal."))
    return issues


def _check_amount_limits(entry: dict, row: int) -> list[dict]:
    issues = []
    try:
        amount = float(entry.get("Amount Requested (PKR)") or 0)
    except (ValueError, TypeError):
        return []
    if amount > MAX_SINGLE_WITHDRAWAL:
        issues.append(_issue(row, entry, "warning", "HIGH_VALUE",
                             f"Amount PKR {amount:,.0f} exceeds single-withdrawal limit of PKR {MAX_SINGLE_WITHDRAWAL:,.0f}."))
    if amount <= 0:
        issues.append(_issue(row, entry, "error", "ZERO_AMOUNT",
                             "Withdrawal amount is zero or negative."))
    return issues


def _check_balance(entry: dict, row: int) -> list[dict]:
    issues = []
    try:
        amount  = float(entry.get("Amount Requested (PKR)") or 0)
        balance = float(entry.get("PF Balance (PKR)") or 0)
    except (ValueError, TypeError):
        return []
    if balance > 0 and amount > balance:
        issues.append(_issue(row, entry, "error", "EXCEEDS_BALANCE",
                             f"Requested PKR {amount:,.0f} exceeds PF balance of PKR {balance:,.0f}."))
    return issues


def _check_hr_not_found(entry: dict, row: int) -> list[dict]:
    # Confidence column contains "low" for unknown employees if extraction agent marks it
    emp_idx = entry.get("Employee Index", "")
    name    = entry.get("Name", "")
    if emp_idx and not name:
        return [_issue(row, entry, "warning", "UNKNOWN_EMPLOYEE",
                       f"Employee '{emp_idx}' not found in HR database.")]
    return []


def _check_duplicates(entries: list[dict]) -> list[dict]:
    """Flag same employee appearing more than once today."""
    seen: dict[str, int] = {}   # emp_index → first row
    issues = []
    for entry in entries:
        idx = (entry.get("Employee Index") or "").strip().upper()
        if not idx:
            continue
        row = entry["_row"]
        if idx in seen:
            issues.append(_issue(row, entry, "error", "DUPLICATE_TODAY",
                                 f"Duplicate entry: '{idx}' already appears in row {seen[idx]} today."))
        else:
            seen[idx] = row
    return issues


# ── AI-based check ────────────────────────────────────────────────────────────

def _check_with_claude(entries: list[dict]) -> list[dict]:
    if not entries:
        return []

    payload = [
        {
            "row": e["_row"],
            "employee_index": e.get("Employee Index"),
            "name": e.get("Name"),
            "grade": e.get("Grade"),
            "pf_balance": e.get("PF Balance (PKR)"),
            "amount": e.get("Amount Requested (PKR)"),
            "reason": e.get("Reason"),
            "confidence": e.get("Confidence"),
        }
        for e in entries
    ]

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": VALIDATION_SYSTEM},
                {"role": "user", "content": f"Review these {len(payload)} PF withdrawal entries for today:\n\n{json.dumps(payload, indent=2)}"},
            ],
        )
        raw = response["message"]["content"].strip()

        # Find JSON array in response even if model adds extra text
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start == -1 or end == 0:
            logger.warning("Ollama validation returned no JSON array, skipping AI check")
            return []

        raw = raw[start:end]
        result = json.loads(raw)

        # Make sure it is a list
        if not isinstance(result, list):
            return []

        # Make sure each item has required keys with correct types
        cleaned = []
        for item in result:
            if not isinstance(item, dict):
                continue
            cleaned.append({
                "row":            int(item.get("row", 0)),
                "employee_index": str(item.get("employee_index", "")),
                "severity":       str(item.get("severity", "warning")),
                "code":           str(item.get("code", "UNKNOWN")),
                "description":    str(item.get("description", "")),
            })
        return cleaned

    except json.JSONDecodeError as e:
        logger.error("Ollama validation returned invalid JSON: {}", e)
        return []
    except Exception as e:
        logger.error("Ollama validation error: {}", e)
        return []
# ── Public entry point ────────────────────────────────────────────────────────

def validate_today() -> dict:
    """
    Run full validation on today's entries.

    Returns a summary dict:
    {
      "total": int,
      "ok": int,
      "warnings": int,
      "errors": int,
      "issues": [{ row, employee_index, severity, code, description }]
    }
    """
    entries = get_today_entries()
    if not entries:
        logger.info("No entries to validate today.")
        return {"total": 0, "ok": 0, "warnings": 0, "errors": 0, "issues": []}

    all_issues: list[dict] = []

    # Rule-based
    for entry in entries:
        row = entry["_row"]
        all_issues += _check_missing_fields(entry, row)
        all_issues += _check_amount_limits(entry, row)
        all_issues += _check_balance(entry, row)
        all_issues += _check_hr_not_found(entry, row)

    all_issues += _check_duplicates(entries)

    # AI-based
    ai_issues = _check_with_claude(entries)
    all_issues += ai_issues

    # Deduplicate by (row, code)
    seen_keys = set()
    deduped = []
    for iss in all_issues:
        key = (iss.get("row"), iss.get("code"))
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(iss)
    all_issues = deduped

    # Map row → worst severity
    row_status: dict[int, str] = {}
    for iss in all_issues:
        row = iss["row"]
        current = row_status.get(row, "OK")
        if iss["severity"] == "error":
            row_status[row] = "Error"
        elif iss["severity"] == "warning" and current == "OK":
            row_status[row] = "Warning"

    # Write status back to Excel
    for entry in entries:
        row     = entry["_row"]
        wb_path = entry["_wb_path"]
        status  = row_status.get(row, "OK")
        notes   = "; ".join(
            i["code"] for i in all_issues if i["row"] == row
        )
        update_validation_status(wb_path, row, status, notes)

    summary = {
        "total":    len(entries),
        "ok":       sum(1 for e in entries if row_status.get(e["_row"], "OK") == "OK"),
        "warnings": sum(1 for v in row_status.values() if v == "Warning"),
        "errors":   sum(1 for v in row_status.values() if v == "Error"),
        "issues":   all_issues,
    }

    logger.info(
        "Validation complete — total={} ok={} warnings={} errors={}",
        summary["total"], summary["ok"], summary["warnings"], summary["errors"],
    )
    return summary


def _issue(row: int, entry: dict, severity: str, code: str, description: str) -> dict:
    return {
        "row":             row,
        "employee_index":  entry.get("Employee Index", ""),
        "severity":        severity,
        "code":            code,
        "description":     description,
    }
