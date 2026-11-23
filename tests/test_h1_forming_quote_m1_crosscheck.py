"""Strict regression tests: H1 forming spread is not M1 execution spread.

All OHLC below are synthetic. No API credentials, broker orders or fills.
"""
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

from trader.market import Snapshot, evaluate_snapshot
from trader.mtf import TIMEFRAMES, evaluate_timeframes, fetch_all_timeframes


NOW = datetime(2026, 11, 23, 16, 31, tzinfo=timezone.utc)
END = {
    "MINUTE": "2026-11-23T16:31:00Z",
    "MINUTE_5": "2026-11-23T16:35:00Z",
    "MINUTE_15": "2026-11-23T16:45:00Z",
    "HOUR": "2026-11-23T17:00:00Z",
}
FREQ = {"MINUTE": "min", "MINUTE_5": "5min",
        "MINUTE_15": "15min", "HOUR": "h"}


def _ohlc(tf, *, closed_spread=0.4, forming_spread=0.4,
          hole_last_20=False):
    idx = pd.date_range(end=END[tf], periods=105, freq=FREQ[tf])
    prices = [7200.0 + i * 0.15 for i in range(len(idx))]
    frame = pd.DataFrame({
        "Open": prices,
        "High": [v + 1 for v in prices],
        "Low": [v - 1 for v in prices],
        "Close": prices,
        "Spread": [closed_spread] * (len(idx)-1) + [forming_spread],
    }, index=idx)
    if hole_last_20:
        frame = frame.drop(frame.index[-13:-8])
    return frame


def _snapshots(*, m1_forming=0.4, h1_forming=6.2,
               h1_closed=0.4, h1_hole=False):
    out={}
    for tf in TIMEFRAMES:
        frame=_ohlc(
            tf,
            closed_spread=h1_closed if tf=="HOUR" else 0.4,
            forming_spread=(m1_forming if tf=="MINUTE"
                            else h1_forming if tf=="HOUR" else 0.4),
            hole_last_20=(h1_hole and tf=="HOUR"),
        )
        out[tf]=evaluate_snapshot(frame,"US500",tf,now=NOW)
    return out


def _fetch(snapshots):
    calls=[]
    class Client:
        def candles(self,epic,tf,*,count,max_spread):
            calls.append((epic,tf,count,max_spread))
            return snapshots[tf]
    items,failures=fetch_all_timeframes(Client(),"US500",count=350)
    return items,failures,calls


def test_anomalous_forming_h1_quote_can_be_crosschecked_with_valid_m1():
    original=_snapshots()
    assert original["MINUTE"].good
    assert not original["HOUR"].good
    assert original["HOUR"].reason=="Bieżący spread: 6.20 > 2.00"
    fetched,failures,calls=_fetch(original)
    assert not failures
    assert len(calls)==4  # no speculative extra broker requests
    assert fetched["HOUR"].good
    assert fetched["HOUR"].frame.equals(original["HOUR"].frame)
    assert fetched["HOUR"].spread==original["HOUR"].spread
    assert "M1_CURRENT_SPREAD_VERIFIED" in fetched["HOUR"].reason
    rows,_=evaluate_timeframes(fetched,now=NOW,asof=fetched["MINUTE"].confirmed_utc)
    assert len(rows)==4 and all(v.ready for v in rows)


def test_h1_closed_spread_over_limit_is_never_bypassed():
    original=_snapshots(h1_closed=3.0)
    assert original["HOUR"].reason.startswith("Spread zamkniętej świecy")
    fetched,_,_=_fetch(original)
    assert fetched["HOUR"] is original["HOUR"]
    assert not fetched["HOUR"].good


def test_m1_live_quote_spread_over_limit_is_never_bypassed():
    original=_snapshots(m1_forming=3.0)
    assert not original["MINUTE"].good
    fetched,_,_=_fetch(original)
    assert fetched["HOUR"] is original["HOUR"]
    assert not fetched["HOUR"].good


def test_unverified_h1_ohlc_hole_remains_blocked():
    original=_snapshots(h1_hole=True)
    assert "Bieżący spread" in original["HOUR"].reason
    fetched,_,_=_fetch(original)
    assert not fetched["HOUR"].good


def test_wrong_feed_and_untimely_h1_remain_blocked():
    for variant in (
        lambda s: replace(s,source="Capital.com LIVE REST"),
        lambda s: replace(s,age_seconds=99999.),
        lambda s: replace(s,quote_spread=float("nan")),
        lambda s: replace(s,confirmed_utc=datetime(2026,11,23,14,0,tzinfo=timezone.utc)),
    ):
        original=_snapshots()
        original["HOUR"]=variant(original["HOUR"])
        fetched,_,_=_fetch(original)
        assert fetched["HOUR"] is original["HOUR"]
        assert not fetched["HOUR"].good


def test_unrecognized_or_corrupt_h1_failure_is_never_bypassed():
    original=_snapshots()
    for reason in ("DANE_WADLIWE: H1", "Bieżący spread: bad text",
                   "Bieżący spread: 0.40 > 2.00"):
        current=dict(original)
        current["HOUR"]=replace(original["HOUR"],reason=reason)
        fetched,_,_=_fetch(current)
        assert not fetched["HOUR"].good
