"""Read-only audit of CLOSED OHLC chronology; never fill missing bars.

This module distinguishes calendar discontinuities from verified feed
completeness. It DOES NOT assert a broker session schedule and cannot
prove that unobserved timestamps correspond to missing broker candles.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

STEP_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "HOUR": 60,
}
WEEKEND = "WEEKEND_OVERLAP"
ROLLOVER = "DAILY_BREAK_CANDIDATE"
REVIEW = "INTRADAY_REVIEW"


def _weekend_between(start: pd.Timestamp, end: pd.Timestamp) -> bool:
    # A discontinuity crossing a weekend is compatible with market closure,
    # but we never assert that the broker was closed for all of it.
    if (end - start) > pd.Timedelta(days=8):
        return True  # Long unknown gaps must still be reviewed by caller.
    day = start.normalize()
    while day <= end.normalize():
        if day.weekday() in (5, 6):
            return True
        day += pd.Timedelta(days=1)
    return False


def audit_closed_candle_gaps(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Describe gaps in one *observed sample*, without changing the OHLC."""
    if timeframe not in STEP_MINUTES:
        raise ValueError("Nieznany interwal.")
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Oczekiwano tabeli OHLC z indeksem czasu.")
    index = frame.index
    if index.tz is None or index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("Niepoprawne znaczniki UTC, kolejnosc lub duplikaty.")
    utc = index.tz_convert("UTC")
    step = pd.Timedelta(minutes=STEP_MINUTES[timeframe])
    if any(t.value % step.value != 0 for t in utc):
        raise ValueError("Swiece nie sa wyrownane do interwalu.")
    issues = []
    for left, right in zip(utc[:-1], utc[1:]):
        delta = right - left
        if delta == step:
            continue
        if delta < step or delta % step:
            raise ValueError("Nieprawidlowa odleglosc miedzy swiecami.")
        slots = int(delta // step) - 1
        weekend = _weekend_between(left, right)
        if delta > pd.Timedelta(days=8):
            kind = REVIEW
        elif weekend:
            kind = WEEKEND
        elif (delta <= pd.Timedelta(minutes=15)
              and left.date() == right.date()
              and left.hour == 22):
            # Only an observed regularity near 22:00 UTC, not a
            # verified Capital.com trading calendar.
            kind = ROLLOVER
        else:
            kind = REVIEW
        issues.append({
            "timeframe": timeframe,
            "previous_utc": left.isoformat(),
            "next_utc": right.isoformat(),
            "gap_minutes": int(delta / pd.Timedelta(minutes=1)),
            "unobserved_slots": slots,
            "classification": kind,
        })
    return pd.DataFrame(
        issues,
        columns=["timeframe", "previous_utc", "next_utc", "gap_minutes",
                 "unobserved_slots", "classification"],
    )


def summarize_gap_audit(gaps: pd.DataFrame, *, timeframe: str,
                        candles: int, first_utc=None, last_utc=None) -> dict:
    """Summarize only loaded window; never claim this is full archive."""
    if timeframe not in STEP_MINUTES or candles < 0:
        raise ValueError("Niepoprawny interwal lub liczba swiec.")
    by_kind = (gaps["classification"].value_counts().to_dict()
               if not gaps.empty else {})
    return {
        "timeframe": timeframe,
        "sample_candles": int(candles),
        "sample_first_utc": str(first_utc) if first_utc is not None else "",
        "sample_last_utc": str(last_utc) if last_utc is not None else "",
        "gaps_total": int(len(gaps)),
        "weekend_overlap": int(by_kind.get(WEEKEND, 0)),
        "daily_break_candidate": int(by_kind.get(ROLLOVER, 0)),
        "requires_review": int(by_kind.get(REVIEW, 0)),
        "unobserved_slots_total": int(gaps["unobserved_slots"].sum())
            if not gaps.empty else 0,
    }
