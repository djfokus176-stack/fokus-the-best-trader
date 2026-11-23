"""Regression for Capital API presumed OPEN-labelled candles (DEMO probe).

2026-11-05 20:24:17 UTC API last M1 snapshotTimeUTC 20:24:00.
This supports OPEN-time labeling, not vendor's formal documentation proof.
"""
import pytest
import pandas as pd
from trader.market import (
    CapitalReadOnly,FeedError,PERIOD,parse_prices,
    capital_prices_as_close_times,evaluate_snapshot)


def demo_raw(tf="MINUTE",n=80):
    step=PERIOD[tf]
    end=pd.Timestamp("2026-11-05T20:24:00Z")
    end=pd.Timestamp((int(end.timestamp())//step)*step,unit="s",tz="UTC")
    ix=pd.date_range(end=end,periods=n,freq=f"{step}s")
    frame=pd.DataFrame({
        "Open":[100.]*n,"High":[101.]*n,"Low":[99.]*n,
        "Close":[100.]*n,"Spread":[.6]*n},index=ix)
    return frame


@pytest.mark.parametrize("tf",["MINUTE","MINUTE_5","MINUTE_15","HOUR"])
def test_open_to_close_exact_shift_for_all_timeframes(tf):
    raw=demo_raw(tf)
    shifted=capital_prices_as_close_times(raw,tf)
    assert shifted.index[0]==raw.index[0]+pd.Timedelta(seconds=PERIOD[tf])
    assert shifted.index[-1]==raw.index[-1]+pd.Timedelta(seconds=PERIOD[tf])
    assert list(shifted.Close.to_numpy())==list(raw.Close.to_numpy())
    assert raw.index[-1]!=shifted.index[-1]
    with pytest.raises(FeedError):
        capital_prices_as_close_times(shifted,tf)


def test_newest_open_label_removed_and_previous_candle_has_true_close_time():
    raw=demo_raw()
    shifted=capital_prices_as_close_times(raw,"MINUTE")
    # Raw 20:24 bar is FORMING at 20:24:17 and must NOT be evaluated.
    snap=evaluate_snapshot(shifted,"US500","MINUTE",
        now=pd.Timestamp("2026-11-05T20:24:17Z").to_pydatetime(),
        source="Capital.com DEMO REST")
    assert snap.good
    assert snap.confirmed_utc==pd.Timestamp("2026-11-05T20:24:00Z").to_pydatetime()
    assert snap.frame.index[-1]==pd.Timestamp("2026-11-05T20:24:00Z")
    assert len(snap.frame)==len(raw)-1
    assert snap.age_seconds==17
    assert shifted.index[-1]==pd.Timestamp("2026-11-05T20:25:00Z")


def test_raw_api_diagnostic_has_no_shift_and_candles_normalize(monkeypatch):
    client=CapitalReadOnly("test","email","password","DEMO")
    times=pd.date_range(end="2026-11-05T20:24:00Z",periods=80,freq="min")
    prices=[]
    for stamp in times:
        price={
            "bid":100.0,"ask":100.6}
        prices.append({
            "snapshotTimeUTC":stamp.isoformat(),
            "openPrice":dict(price),
            "highPrice":{"bid":101,"ask":101.6},
            "lowPrice":{"bid":99,"ask":99.6},
            "closePrice":dict(price)})
    class Resp:
        def raise_for_status(self):return None
        def json(self):return {"prices":prices}
    monkeypatch.setattr(client,"headers",lambda:{"CST":"stub","X-SECURITY-TOKEN":"stub"})
    monkeypatch.setattr(client.session,"get",lambda *a,**kw:Resp())
    seen=client.raw_candle_time_diagnostic("US500","MINUTE")
    assert seen.index[-1]==pd.Timestamp("2026-11-05T20:24:00Z")
    # Don't use real clock in this test. The content is historical so
    # .good can be false; the close-time index still must be correct.
    snap=client.candles("US500","MINUTE")
    assert snap.frame.index[-1]==pd.Timestamp("2026-11-05T20:24:00Z")
    assert snap.frame.index[-1] != seen.index[-2]
    assert snap.frame.index.equals(seen.index[:-1]+pd.Timedelta(minutes=1))


def test_misaligned_api_clock_blocks_instead_of_guessing():
    f=demo_raw()
    f.index=f.index+pd.Timedelta(seconds=5)
    with pytest.raises(FeedError,match="UTC"):
        capital_prices_as_close_times(f,"MINUTE")
