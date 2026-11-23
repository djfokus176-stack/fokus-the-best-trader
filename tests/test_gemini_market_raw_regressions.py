"""Regression tests for Gemini-audited, independently confirmed code defects.

No real prices, no broker orders and no inference of profits from missing bars.
"""
import pandas as pd

from trader.market import capital_prices_as_close_times, evaluate_snapshot
from trader.raw_m1_forward_paper import advance_raw_paper, raw_paper_report


def _h1_with_old_corrupt_bar(*, corrupted_at=15):
    first=pd.date_range(end="2026-11-20T21:00:00Z",periods=100,freq="h")
    following=pd.date_range(start="2026-11-22T23:00:00Z",periods=16,freq="h")
    index=first.append(following)
    bad=index[corrupted_at]
    frame=pd.DataFrame({"Open":100.0,"High":101.0,"Low":99.0,
                        "Close":100.0,"Spread":0.5},index=index)
    # Vendor's quarantined bar was removed; never reinsert it.
    frame=frame.drop(bad)
    frame.attrs["quarantined_candles"]=(
        {"candle_utc":bad.isoformat(),"issue":"Close: bid > ask"},)
    now=index[-1].to_pydatetime()
    return frame,now,bad


def test_h1_old_corrupt_candle_can_be_quarantined_across_verified_weekend():
    frame,now,bad=_h1_with_old_corrupt_bar(corrupted_at=15)
    snap=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert snap.good, snap.reason
    assert bad not in snap.frame.index
    assert "POMINIĘTO_STARE_BŁĘDY" in snap.reason


def test_h1_recent_corrupt_stays_blocked_after_weekend():
    frame,now,_=_h1_with_old_corrupt_bar(corrupted_at=82)
    snap=evaluate_snapshot(frame,"US500","HOUR",now=now)
    assert not snap.good
    assert "DANE_WADLIWE" in snap.reason


def test_vendor_quarantined_open_label_is_shifted_to_same_close_clock():
    index=pd.date_range("2026-11-20T15:00:00Z",periods=80,freq="h")
    raw=pd.DataFrame({"Open":100.,"High":101.,"Low":99.,
                      "Close":100.,"Spread":0.5},index=index)
    original="2026-11-20T17:00:00+00:00"
    raw.attrs["quarantined_candles"]=(
        {"candle_utc":original,"issue":"Close: bid > ask"},)
    shifted=capital_prices_as_close_times(raw,"HOUR")
    rec=shifted.attrs["quarantined_candles"][0]
    assert rec["raw_open_utc"]==original
    assert pd.Timestamp(rec["candle_utc"])==pd.Timestamp(original)+pd.Timedelta(hours=1)
    assert shifted.index[0]==raw.index[0]+pd.Timedelta(hours=1)


def _m1(count=100):
    times=pd.date_range("2026-11-23T08:00:00Z",periods=count,freq="min")
    prices=[7400+i*0.10 for i in range(count)]
    return pd.DataFrame({"Open":prices,"High":[x+1 for x in prices],
                         "Low":[x-1 for x in prices],"Close":prices,
                         "Spread":[0.4]*count},index=times)


def _raw_vote():
    return [{"Strategia":"EMA TREND","Setup OHLC":"LONG",
             "Po filtrze MTF":"WAIT"}]


def test_recovered_scan_is_not_falsely_counted_as_market_data_hole():
    starting=advance_raw_paper({},_m1(95),_raw_vote(),spread=.4)
    opened=advance_raw_paper(starting,_m1(96),_raw_vote(),spread=.4)
    assert opened["active"]["status"]=="OPEN"
    recovered=advance_raw_paper(opened,_m1(100),_raw_vote(),spread=.4)
    report=raw_paper_report(recovered)
    assert report["gaps"]==0
    assert report["scan_skips_recovered"]==1
    assert report["gaps_recovered"]==1
    assert report["recovered_bars"]==4
    assert report["recovered_bars_idle"]==0


def test_idle_skipped_scan_reports_no_replayed_position_bars():
    starting=advance_raw_paper({},_m1(95),_raw_vote(),spread=.4)
    starting["active"]=None
    recovered=advance_raw_paper(starting,_m1(100),_raw_vote(),spread=.4)
    report=raw_paper_report(recovered)
    assert report["gaps"]==0
    assert report["scan_skips_recovered"]==1
    assert report["recovered_bars"]==0
    assert report["recovered_bars_idle"]==5
    assert report["closed_total"]==0


def test_true_missing_m1_still_counts_hole_not_recovered():
    starting=advance_raw_paper({},_m1(95),_raw_vote(),spread=.4)
    opened=advance_raw_paper(starting,_m1(96),_raw_vote(),spread=.4)
    frame=_m1(100).drop(_m1(100).index[97])
    state=advance_raw_paper(opened,frame,_raw_vote(),spread=.4)
    report=raw_paper_report(state)
    assert report["gaps"]==1
    assert report["scan_skips_recovered"]==0
    assert report["invalidated_after_open"]==1
    assert report["closed_total"]==0
