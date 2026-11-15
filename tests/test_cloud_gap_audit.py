"""OHLC gap audit must not pretend weekend or maintenance are verified."""
import pandas as pd
import pytest

from trader.cloud_gap_audit import (
    audit_closed_candle_gaps, summarize_gap_audit,
    WEEKEND, ROLLOVER, REVIEW,
)


def _frame(stamps):
    return pd.DataFrame({"Close": [100.] * len(stamps)},
                        index=pd.DatetimeIndex(stamps, tz="UTC"))


def test_classifies_weekend_maintenance_candidate_and_unexplained_intraday():
    stamps = [
        "2026-11-06 21:55", "2026-11-06 22:00",
        "2026-11-08 23:00", "2026-11-08 23:05",
        "2026-11-09 22:00", "2026-11-09 22:10",
        "2026-11-10 03:00", "2026-11-10 05:00",
    ]
    gaps = audit_closed_candle_gaps(_frame(stamps), "MINUTE_5")
    assert len(gaps) == 4
    # Sunday opening following a Friday close is not called corruption.
    assert gaps.iloc[0]["classification"] == WEEKEND
    assert gaps.iloc[0]["unobserved_slots"] == 587
    assert gaps.iloc[1]["classification"] == REVIEW
    assert gaps.iloc[2]["classification"] == ROLLOVER
    assert gaps.iloc[2]["unobserved_slots"] == 1
    assert gaps.iloc[3]["classification"] == REVIEW
    summary = summarize_gap_audit(gaps, timeframe="MINUTE_5", candles=len(stamps),
                                  first_utc=stamps[0], last_utc=stamps[-1])
    assert summary["gaps_total"] == 4
    assert summary["requires_review"] == 2
    assert summary["daily_break_candidate"] == 1
    assert summary["weekend_overlap"] == 1


def test_no_gaps_is_not_zero_unseen_history_claim():
    frame = _frame(["2026-11-09 12:00", "2026-11-09 12:01"])
    gaps = audit_closed_candle_gaps(frame, "MINUTE")
    assert gaps.empty
    summary = summarize_gap_audit(gaps, timeframe="MINUTE", candles=2)
    assert summary["gaps_total"] == 0
    assert summary["sample_candles"] == 2


def test_reject_duplicates_naive_and_unaligned_labels():
    f = _frame(["2026-11-09 12:00", "2026-11-09 12:00"])
    with pytest.raises(ValueError, match="duplikaty"):
        audit_closed_candle_gaps(f, "MINUTE")
    naive = f.copy()
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError):
        audit_closed_candle_gaps(naive, "MINUTE")
    with pytest.raises(ValueError, match="wyrownane"):
        audit_closed_candle_gaps(_frame(["2026-11-09 12:01"]), "MINUTE_5")


def test_large_gap_requires_review_not_weekend_proof():
    f = _frame(["2026-11-06 21:00", "2026-11-20 21:00"])
    g = audit_closed_candle_gaps(f, "HOUR")
    assert g.iloc[0]["classification"] == REVIEW
