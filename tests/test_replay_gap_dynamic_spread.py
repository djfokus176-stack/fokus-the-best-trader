"""Regression coverage: missing M1 must never manufacture PAPER P&L.

Dynamic spread uses only already-known signal/previous-close observations
for intrabar fills. These synthetic candles are NOT live profitability proof.
"""
import numpy as np
import pandas as pd
import pytest
from trader import research
from trader.strategy import Decision, simulate_outcome


def candles(n=150):
    idx=pd.date_range("2026-11-10T12:00:00Z",periods=n,freq="min",tz="UTC")
    mid=5000+np.arange(n)*.04
    return pd.DataFrame({"Open":mid,"Close":mid+.02,
                         "High":mid+.3,"Low":mid-.3,
                         "Spread":np.full(n,.4)},index=idx)


def single_signal(monkeypatch,stamp, *, target_distance=100.0):
    def decide(prefix,strategy,spread):
        if prefix.index[-1]!=stamp:
            return Decision("WAIT",strategy,"No other signals")
        price=float(prefix.Close.iloc[-1])
        return Decision("LONG",strategy,"Synthetic candidate",
                        price,price-100,price+target_distance,1.6)
    monkeypatch.setattr(research,"decide_any",decide)


def test_missing_minutes_during_open_trade_invalidates_not_timeout(monkeypatch):
    x=candles()
    signal=x.index[89]
    single_signal(monkeypatch,signal)
    # The first two future candles are visible; four subsequent M1 are gone.
    x=x.drop(x.index[92:96])
    t=research.replay(x,"EMA TREND",holding=5,evaluation_start=90,spread=.4)
    assert len(t)==1
    assert t.iloc[0].status=="INVALIDATED_GAP"
    assert pd.isna(t.iloc[0].pnl_pts)
    result=research.stats(t)
    assert result["n"]==0 and result["invalidated_gaps"]==1
    assert result["sum_pts"]==0.0


def test_first_future_bar_missing_cannot_be_assumed_entry(monkeypatch):
    x=candles()
    signal=x.index[89]
    single_signal(monkeypatch,signal)
    x=x.drop(signal+pd.Timedelta(minutes=1))
    t=research.replay(x,"EMA TREND",holding=5,evaluation_start=90,spread=.4)
    assert len(t)==1 and t.iloc[0].status=="INVALIDATED_GAP"


def test_later_gap_does_not_erase_previously_confirmed_tp(monkeypatch):
    x=candles()
    signal=x.index[89]
    single_signal(monkeypatch,signal,target_distance=.15)
    x=x.drop(x.index[92:96])
    t=research.replay(x,"EMA TREND",holding=5,evaluation_start=90,spread=.4)
    assert len(t)==1 and t.iloc[0].status=="WIN"
    assert research.stats(t)["invalidated_gaps"]==0


def test_single_closed_bar_can_reach_target():
    idx=pd.date_range("2026-11-10",periods=1,freq="min",tz="UTC")
    one=pd.DataFrame({"Open":[100.],"High":[103.],"Low":[99.7],
                      "Close":[102.]},index=idx)
    status,pnl=simulate_outcome(one,"LONG",100,99,102,.4,slippage=.25)
    assert status=="WIN" and pnl>0


def test_historical_spread_changes_timeout_costs(monkeypatch):
    x=candles()
    signal=x.index[89]
    single_signal(monkeypatch,signal)
    # First signal-close spread is 0.40; timeout close spread is 2.00.
    x.loc[x.index[93],"Spread"]=2.0
    fixed=research.replay(x,"EMA TREND",holding=4,evaluation_start=90,
                          spread=.4,spread_mode="fixed")
    historical=research.replay(x,"EMA TREND",holding=4,evaluation_start=90,
                               spread=.4,spread_mode="historical")
    assert len(fixed)==len(historical)==1
    assert fixed.iloc[0].status==historical.iloc[0].status=="TIMEOUT"
    assert historical.iloc[0].entry_spread==.4
    assert historical.iloc[0].exit_spread==2.0
    assert fixed.iloc[0].pnl_pts-historical.iloc[0].pnl_pts==pytest.approx(.8)


def test_no_lookahead_from_exit_bars_spread_into_first_bar_tp(monkeypatch):
    x=candles()
    signal=x.index[89]
    single_signal(monkeypatch,signal,target_distance=.15)
    # Spread at the NEXT candle's close isn't knowable at entry/TP time.
    x.loc[x.index[90],"Spread"]=8.0
    fixed=research.replay(x,"EMA TREND",holding=5,evaluation_start=90,
                          spread=.4,spread_mode="fixed")
    historical=research.replay(x,"EMA TREND",holding=5,evaluation_start=90,
                               spread=.4,spread_mode="historical")
    assert fixed.iloc[0].status==historical.iloc[0].status=="WIN"
    assert historical.iloc[0].entry_spread==historical.iloc[0].exit_spread==.4
    assert historical.iloc[0].pnl_pts==fixed.iloc[0].pnl_pts


def test_historical_spread_rejects_missing_invalid_or_unknown_mode():
    x=candles()
    with pytest.raises(ValueError,match="Spread"):
        research.replay(x.drop(columns=["Spread"]),"EMA TREND",
                        spread_mode="historical")
    x.loc[x.index[91],"Spread"]=-1
    with pytest.raises(ValueError):
        research.replay(x,"EMA TREND",spread_mode="historical")
    with pytest.raises(ValueError):
        research.replay(candles(),"EMA TREND",spread_mode="future")
