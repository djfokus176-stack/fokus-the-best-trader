"""Automatic, bounded and strictly causal A–E research on fresh M15 closes.

No orders, no AUTO inputs, no database tables or altered PAPER fills.
First observed snapshot only primes a watermark: historical A–E candidates
are never silently reclassified as FORWARD. New candidates are evaluated by
the SAME run_wave_abcd research engine using only fully observed candles.
Variant-level resolved results are immutable; a later repaired history cannot
silently rewrite prior forward outcomes.

A–E variants from one anchor are correlated, and the original 70/30 split
is already exposed. All samples are exploratory and trade permission WAIT.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

import pandas as pd

from .wave_intelligence2 import VARIANTS, run_wave_abcd
from .wave_reversal import validate_closed_m15

SCHEMA = "wave_ae_forward_v1"
MAX_ANCHORS = 120
MIN_BARS = 210
STATUS_EMPTY = "NO_NEW_FORWARD_ANCHOR"
RESOLVED = ("TP", "SL", "TIMEOUT", "SESSION_TIMEOUT")
SOURCE = "Capital.com DEMO REST"


def _utc(v):
    d = pd.Timestamp(v)
    if d.tzinfo is None or pd.isna(d):
        raise ValueError("WAVE A-E: requires UTC-aware timestamps")
    return d.tz_convert("UTC")


def _safe_number(v):
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(f, 4) if isfinite(f) else None


def _optional_utc(v):
    if v is None or pd.isna(v):
        return None
    return _utc(v).isoformat()


def _variant_from_row(row):
    """Whitelisted JSON-only fields; no pandas NA or untrusted objects."""
    status = str(row["status"])
    pnl = _safe_number(row.get("pnl_pts"))
    if status in RESOLVED and pnl is None:
        raise ValueError("WAVE A-E: resolved trade without finite net PnL")
    return {
        "variant": str(row["variant"]),
        "side": str(row.get("direction", "")),
        "status": status,
        "triggered": bool(row.get("triggered", False)),
        "signal_utc": _optional_utc(row.get("signal_utc")),
        "entry_utc": _optional_utc(row.get("entry_utc")),
        "exit_utc": _optional_utc(row.get("exit_utc")),
        "pnl_pts": pnl,
        "execution": (str(row.get("execution")) if pd.notna(
            row.get("execution")) else None),
    }


def advance_wave_ae_forward(state, frame, *, epic="US500",
                            source=SOURCE, max_anchors=MAX_ANCHORS):
    """Advance at most once per new CLOSED M15, with an initial cold primer.

    Only anchors whose confirmed SIGNAL candle arrives AFTER our initial
    saved watermark join the FORWARD cohort; old anchors update when their
    own genuinely later B/C/D triggers and exits have been observed.
    """
    if source != SOURCE or epic != "US500":
        raise ValueError("WAVE A-E: unsupported source/epic")
    if not 20 <= max_anchors <= MAX_ANCHORS:
        raise ValueError("WAVE A-E: invalid archive cap")
    validate_closed_m15(frame)
    last = frame.index[-1].tz_convert("UTC")
    old = dict(state or {})
    if old and old.get("schema") != SCHEMA:
        raise ValueError("WAVE A-E: unknown existing checkpoint schema")
    previous = _utc(old["last_closed_utc"]) if old.get("last_closed_utc") else None
    if previous is not None and last < previous:
        raise ValueError("WAVE A-E: stale broker history cannot rewind watermark")
    if previous is not None and last == previous:
        return old
    events = list(old.get("events") or [])
    ids = [e.get("anchor_id") for e in events]
    if len(ids) != len(set(ids)) or len(events) > MAX_ANCHORS:
        raise ValueError("WAVE A-E: duplicate/corrupt persisted anchors")
    if previous is None:
        return {
            "schema": SCHEMA, "epic": epic, "source": source,
            "last_closed_utc": last.isoformat(),
            "initialized_utc": datetime.now(timezone.utc).isoformat(),
            "events": [], "status": "PRIMED_NO_HISTORICAL_BACKFILL",
            "trade_permission": "WAIT",
        }
    if len(frame) < MIN_BARS:
        return {**old, "last_closed_utc": last.isoformat(),
                "status": "INSUFFICIENT_M15",
                "trade_permission": "WAIT"}
    # run_wave_abcd uses causally confirmed pivot indices, real OHLC
    # closes and NEXT-bar hypothetical entries. No retrospective fill for
    # a future candle. The 70/30 division is NOT called new OOS here.
    _, logs, _ = run_wave_abcd(
        frame, spread=2., slippage=.25, rr=1.5, hold_minutes=120)
    if logs is None or logs.empty:
        return {**old, "last_closed_utc": last.isoformat(),
                "status": STATUS_EMPTY, "trade_permission": "WAIT"}
    grouped = {}
    for record in logs.to_dict("records"):
        identifier = str(record["anchor_id"])
        grouped.setdefault(identifier, []).append(record)
    existing = {e["anchor_id"]: e for e in events}
    for identifier, rows in grouped.items():
        anchor_utc = _utc(rows[0]["anchor_utc"])
        if anchor_utc > last:
            raise ValueError("WAVE A-E: future signal in CLOSED candles")
        direction = str(rows[0].get("anchor_side", ""))
        if direction not in ("LONG", "SHORT"):
            raise ValueError("WAVE A-E: bad anchor side")
        variants = {str(x["variant"]): x for x in rows}
        if set(variants) != set(VARIANTS) or len(rows) != len(VARIANTS):
            raise ValueError("WAVE A-E: incomplete five-variant opportunity")
        if identifier not in existing:
            # Critical: historical candidates appearing after reconnect
            # or snapshot expansion are NOT forward observations.
            if anchor_utc <= previous:
                continue
            existing[identifier] = {
                "anchor_id": identifier,
                "anchor_utc": anchor_utc.isoformat(),
                "anchor_side": direction,
                "first_seen_m15_utc": last.isoformat(),
                "variants": {},
            }
        event = existing[identifier]
        if event["anchor_utc"] != anchor_utc.isoformat():
            raise ValueError("WAVE A-E: conflicting anchor identity")
        for name in VARIANTS:
            old_variant = (event.get("variants") or {}).get(name) or {}
            # Never rewrite a previously resolved trade on later scans.
            if old_variant.get("status") in RESOLVED:
                continue
            # Nor turn a prior explicitly invalidated result into PnL.
            if str(old_variant.get("status", "")).startswith("INVALIDATED_"):
                continue
            event.setdefault("variants", {})[name] = _variant_from_row(variants[name])
    values = sorted(existing.values(), key=lambda e:(e["anchor_utc"],e["anchor_id"]))
    values = values[-max_anchors:]
    return {
        "schema": SCHEMA, "epic": epic, "source": source,
        "last_closed_utc": last.isoformat(),
        "initialized_utc": old.get("initialized_utc"),
        "events": values,
        "status": "FORWARD_AE_RESEARCH_ACTIVE",
        "trade_permission": "WAIT",
    }


def wave_ae_forward_scorecard(state):
    """Summarize *one anchor per NY session/side*, not overlapping 5 trades."""
    data = state if isinstance(state, dict) else {}
    events = list(data.get("events") or [])
    rows = []
    for side in ("LONG", "SHORT"):
        cohort = [e for e in events if e.get("anchor_side") == side]
        for variant in VARIANTS:
            summaries = [e.get("variants", {}).get(variant) or {} for e in cohort]
            pnl = [float(v["pnl_pts"]) for v in summaries
                   if v.get("status") in RESOLVED and
                   _safe_number(v.get("pnl_pts")) is not None]
            gross_win = sum(max(0.,x) for x in pnl)
            gross_loss = -sum(min(0.,x) for x in pnl)
            n = len(pnl)
            rows.append({
                "side": side, "variant": variant,
                "anchors": len(cohort), "closed": n,
                "pending_or_untriggered": (0 if variant=="E_WAIT" else sum(
                    v.get("status") not in RESOLVED and
                    not str(v.get("status","")).startswith("INVALIDATED_")
                    for v in summaries)),
                "invalidated": sum(str(v.get("status","")).startswith(
                    "INVALIDATED_") for v in summaries),
                "net_pts": round(sum(pnl), 2) if n else None,
                "expectancy_pts": round(sum(pnl)/n, 3) if n else None,
                "win_pct_descriptive": (
                    round(100*sum(x>0 for x in pnl)/n, 2) if n>=20 else None),
                "profit_factor_descriptive": (
                    round(gross_win/gross_loss, 3)
                    if n>=20 and gross_loss>0 else None),
                "status": ("BENCHMARK WAIT — BRAK TRANSAKCJI" if variant=="E_WAIT"
                            else "BADANIE FORWARD — WAIT; BRAK WALIDACJI PO KOSZTACH"),
            })
    return {
        "schema": SCHEMA,
        "last_closed_utc": data.get("last_closed_utc"),
        "status": data.get("status","NOT_STARTED"),
        "events_forward": len(events),
        "closed_outcomes": sum(r["closed"] for r in rows),
        "rank": rows,
        "trade_permission": "WAIT",
        "independent_oos_verified": False,
        "calibrated_probability": False,
        "cost_model": "M15 historical spread + 0.25pts slippage/side; NO fills",
        "source": SOURCE,
    }
