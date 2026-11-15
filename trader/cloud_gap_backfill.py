"""Bounded, opt-in Capital DEMO archive gap reconciliation.

Only historical closed broker candles are candidates; no interpolation,
no guessed market schedule, no edits to existing rows. One request per
eligible pass, at most once per hour. Never touches AUTO/PAPER decisions.
The worker persists a small cursor in its already versioned checkpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd

from .cloud_gap_audit import (
    STEP_MINUTES, REVIEW, audit_closed_candle_gaps,
)

TIMEFRAMES = tuple(STEP_MINUTES)
MIN_INTERVAL_SECONDS = 3600
PAGE_LIMIT = 1000
MAX_MISSING_SLOTS = 180


def _utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("Backfill wymaga strefy czasowej UTC.")
    return stamp.tz_convert("UTC")


def backfill_pass(remote, broker, prior=None, *, now=None,
                  epic="US500", page_limit=PAGE_LIMIT):
    """Attempt one small, strictly bounded broker-confirmed repair.

    A cursor walks source/epic/TF in reverse chronological order. The
    inclusive cursor overlaps one timestamp to retain boundary gaps.
    Calls are throttled even if the broker has no bars for a candidate.
    Returned counts mean rows *submitted*, not independently proven inserts.
    """
    if getattr(broker, "environment", None) != "DEMO":
        raise ValueError("Automatyczny backfill tylko Capital.com DEMO.")
    if not 3 <= int(page_limit) <= PAGE_LIMIT:
        raise ValueError("Nieprawidlowy rozmiar strony archiwum.")
    if epic != "US500":
        raise ValueError("Backfill wymaga zatwierdzenia innego instrumentu.")
    now = _utc(now if now is not None else datetime.now(timezone.utc))
    state = dict(prior or {})
    last = state.get("last_attempt_utc")
    if last:
        age = (now - _utc(last)).total_seconds()
        if 0 <= age < MIN_INTERVAL_SECONDS:
            return state
    # Save the attempt time even if no candidate is found: protect API limits.
    state["last_attempt_utc"] = now.isoformat()
    tf_index = int(state.get("tf_index", 0))
    if not 0 <= tf_index < len(TIMEFRAMES):
        tf_index = 0
    tf = TIMEFRAMES[tf_index]
    before = state.get("before_utc")
    stamps = remote.fetch_candle_times(epic, tf, before=before,
                                       limit=page_limit)
    if not isinstance(stamps, pd.DatetimeIndex):
        raise ValueError("Supabase nie zwrocil DatetimeIndex.")
    if stamps.tz is None or stamps.has_duplicates or not stamps.is_monotonic_increasing:
        raise ValueError("Niepoprawna kolejnosc/czasy archiwum Supabase.")
    # Move the cursor even when the broker has no available historical bars.
    if len(stamps) >= page_limit:
        state["before_utc"] = stamps[0].isoformat()
    else:
        state["before_utc"] = None
        state["tf_index"] = (tf_index + 1) % len(TIMEFRAMES)
    state.update({"timeframe": tf, "sample_size": len(stamps),
                  "submitted_rows": 0, "status": "NO_ELIGIBLE_GAP"})
    if len(stamps) < 2:
        return state
    frame = pd.DataFrame(index=stamps)
    gaps = audit_closed_candle_gaps(frame, tf)
    choices = gaps.loc[
        (gaps["classification"] == REVIEW)
        & (gaps["unobserved_slots"] <= MAX_MISSING_SLOTS)
        & (gaps["unobserved_slots"] > 0)
    ]
    if choices.empty:
        return state
    # The newest suspect gap first, without implying it is an actual loss.
    target = choices.iloc[-1]
    left = _utc(target["previous_utc"])
    right = _utc(target["next_utc"])
    step = pd.Timedelta(minutes=STEP_MINUTES[tf])
    if right >= now - step:
        state["status"] = "RECENT_OR_OPEN_HORIZON"
        return state
    # Historical broker timestamps are OPEN; archive timestamps are CLOSE.
    # Include the known right-hand neighbor but write only interior bars.
    bars = broker.historical_closed_candles(
        epic, tf, left, right-step,
        max_count=min(PAGE_LIMIT, int(target["unobserved_slots"])+1))
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("Capital nie zwrocil tabeli swiec.")
    if not bars.empty and (not isinstance(bars.index, pd.DatetimeIndex)
            or bars.index.tz is None or bars.index.has_duplicates
            or not bars.index.is_monotonic_increasing):
        raise ValueError("Niepoprawne czasy historycznych swiec Capital.")
    candidates = bars.loc[(bars.index > left) & (bars.index < right)]
    expected = pd.date_range(left+step, right-step, freq=step)
    if not candidates.index.isin(expected).all():
        raise ValueError("Capital zwrocil swiece spoza oczekiwanej siatki.")
    state.update({
        "gap_previous_utc": left.isoformat(),
        "gap_next_utc": right.isoformat(),
        "unobserved_slots": int(target["unobserved_slots"]),
        "broker_rows": len(candidates),
    })
    if candidates.empty:
        state["status"] = "BROKER_NO_MATCHING_BARS"
        return state
    submitted = remote.insert_missing_candles(epic, tf, candidates)
    state["submitted_rows"] = int(submitted)
    state["status"] = "SUBMITTED_VERIFIED_CANDLES"
    return state
