"""Persist minimal sanitized worker scan health for an independent watchdog.

This is monitoring ONLY. It cannot authorize PAPER, alter MTF, disable
broker safeguards, send orders or consume a checkpoint version itself.
Normal no-signal WAIT, planned macro blackouts and market closure are not
reported as system failures.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

FAULT_GATES = (
    "DATA_STALE",
    "INCOMPLETE_MTF",
    "MARKET_NOT_TRADEABLE",
    "MACRO_CALENDAR_UNKNOWN",
    "MACRO_CALENDAR_UNAVAILABLE",
    "PAPER_DAILY_STOP_CONFIG_INVALID",
)
CONFIG_GATES = {"SETUPS_DISABLED"}
RISK_GATES = {"PAPER_DAILY_DRAWDOWN_LIMIT"}
PERSISTENT_FAULT_SCANS = 8


def classify_scan_status(message: str) -> tuple[str, str, bool]:
    """Return (state, reason code, fault), never the raw untrusted log text."""
    if not isinstance(message, str) or not message.strip():
        return "FAULT", "EMPTY_STATUS", True
    # No GATES field is normal during actual broker closure; this branch
    # precedes the live feed/market failure classifications.
    if " / MARKET_CLOSED / " in message:
        return "MARKET_CLOSED", "BROKER_CLOSED", False
    if " / NO_FEED / " in message:
        return "FAULT", "NO_FEED", True
    if " / DATA_STALE / " in message:
        return "FAULT", "DATA_STALE", True
    if " / WORKER ERROR:" in message:
        return "FAULT", "WORKER_ERROR", True
    if "PAPER v3 is DEMO-only" in message:
        return "FAULT", "INVALID_DEMO_CONFIG", True
    match = re.search(r"(?:^| / )GATES=([A-Z0-9_,]+)(?= /|$)", message)
    if match is None:
        return "FAULT", "UNKNOWN_SCAN_STATUS", True
    gates = set(match.group(1).split(","))
    for code in FAULT_GATES:
        if code in gates:
            return "FAULT", code, True
    if gates & CONFIG_GATES:
        return "PAUSED_CONFIG", "SETUPS_DISABLED", False
    if gates & RISK_GATES:
        return "PAUSED_RISK", "PAPER_DAILY_DRAWDOWN_LIMIT", False
    if "MACRO_BLACKOUT" in gates:
        return "PAUSED_MACRO", "MACRO_BLACKOUT", False
    if gates == {"OK"}:
        return "OK", "OK", False
    # Other explicit protective gates are not silently treated as healthy.
    return "PAUSED_OTHER", "OTHER_PROTECTIVE_GATE", False


def advance_scan_quality(message: str, previous=None, *, now=None) -> dict:
    """Maintain a streak across durable worker checkpoints.

    It is intentionally an observational counter: NEVER passed back into
    the strategy engine, PAPER lifecycle, or broker execution code.
    """
    at = now if now is not None else datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("UTC-aware timestamp required")
    at = at.astimezone(timezone.utc).isoformat()
    state, code, is_fault = classify_scan_status(message)
    old = previous if isinstance(previous, dict) else {}
    n = old.get("consecutive_fault_scans", 0)
    if type(n) is not int or n < 0 or n > 1_000_000:
        n = 0
    streak = min(1_000_000, n + 1) if is_fault else 0
    start = old.get("fault_since_utc") if n and is_fault else None
    return {
        "state": state,
        "code": code,
        "consecutive_fault_scans": streak,
        "persistent_fault": bool(streak >= PERSISTENT_FAULT_SCANS),
        "fault_since_utc": start or at if is_fault else None,
        "checked_utc": at,
        "scan_gates_clear": bool(state == "OK"),
    }
