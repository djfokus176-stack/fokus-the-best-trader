"""Watches may show direction early but never become fake PAPER trades."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from trader.early_watch import evaluate_early_watch, recent_watch_markers, annotate_watch_markers
from trader.mtf import timeframe_refresh_needed


def candles(direction=1):
    idx=pd.date_range("2026-11-09T18:00:00+00:00",periods=130,freq="min")
    close=np.array([7540+direction*i*.24 for i in range(len(idx))],dtype=float)
    open_=close-direction*.15
    high=np.maximum(open_,close)+.15
    low=np.minimum(open_,close)-.15
    return pd.DataFrame({"Open":open_,"High":high,"Low":low,
                         "Close":close,"Spread":np.full(len(idx),.4)},index=idx)


def test_strong_closed_m1_trend_shows_informational_long():
    data=candles(1)
    result=evaluate_early_watch(data)
    assert result.side=="LONG",result
    assert result.score>=3
    assert result.countertrend is False
    assert "Bez potwierdzenia PAPER" in result.reason
    marked=recent_watch_markers(data,last_bars=35)
    assert marked and marked[-1]["side"]=="LONG"
    assert marked[-1]["time"]==data.index[-1]


def test_strong_closed_m1_trend_shows_informational_short():
    data=candles(-1)
    result=evaluate_early_watch(data)
    assert result.side=="SHORT",result
    assert result.score>=3
    marked=recent_watch_markers(data,last_bars=35)
    assert marked[-1]["side"]=="SHORT"


def test_watch_is_history_causal_not_forming_candle():
    frame=candles(1)
    original=evaluate_early_watch(frame)
    forming=frame.iloc[[-1]].copy()
    forming.index=forming.index+pd.Timedelta(minutes=1)
    forming.loc[:,["Open","High","Low","Close"]]=[7470,7471,7465,7467]
    newer=pd.concat([frame,forming])
    # A new forming bar must never be passed to informational analysis;
    # the caller evaluates only frame.iloc[:-1].
    assert evaluate_early_watch(newer.iloc[:-1])==original
    assert recent_watch_markers(newer.iloc[:-1])[-1]["time"]==frame.index[-1]


def test_watch_refuses_corruption_and_zero_movement():
    data=candles()
    damaged=data.copy()
    damaged.loc[damaged.index[-1],"High"]=0
    assert evaluate_early_watch(damaged).side=="WAIT"
    flat=data.copy()
    flat.loc[:,["Open","High","Low","Close"]]=[100.,100.2,99.8,100.]
    assert evaluate_early_watch(flat).side=="WAIT"
    naive=data.copy()
    naive.index=naive.index.tz_localize(None)
    assert evaluate_early_watch(naive).side=="WAIT"


def test_cached_missing_mtf_is_refetched_but_never_reused_stale():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    last=now-timedelta(seconds=25)
    snap=SimpleNamespace(good=True,confirmed_utc=last,
                         source="Capital.com DEMO REST",resolution="MINUTE_5")
    assert not timeframe_refresh_needed(None,"MINUTE_5",elapsed=0,anchor_closed=now)
    assert not timeframe_refresh_needed(None,"MINUTE_5",elapsed=30,anchor_closed=now)
    assert timeframe_refresh_needed(None,"MINUTE_5",elapsed=60,anchor_closed=now)
    assert timeframe_refresh_needed(None,"MINUTE_5",elapsed=float("inf"),anchor_closed=now)
    assert not timeframe_refresh_needed(snap,"MINUTE_5",elapsed=20,anchor_closed=now)
    assert not timeframe_refresh_needed(snap,"MINUTE_5",elapsed=90,anchor_closed=now)
    assert timeframe_refresh_needed(snap,"MINUTE_5",elapsed=90,
                                    anchor_closed=now+timedelta(minutes=6))
    assert timeframe_refresh_needed(snap,"MINUTE_5",elapsed=302,anchor_closed=now)
    broken=SimpleNamespace(**{**vars(snap),"good":False})
    assert timeframe_refresh_needed(broken,"MINUTE_5",elapsed=62,anchor_closed=now)
    assert not timeframe_refresh_needed(broken,"MINUTE_5",elapsed=9,anchor_closed=now)


def test_ui_is_exclusively_watch_not_broker_or_paper_queuing():
    root=Path(__file__).resolve().parents[1]
    ui=(root/"app.py").read_text("utf-8")
    src=(root/"trader"/"early_watch.py").read_text("utf-8")
    assert "OBSERWUJ (bez transakcji)" in ui
    assert "POBIERZ PONOWNIE BRAKUJĄCE MTF" in ui
    assert "annotate_watch_markers(fig,snap.frame" in ui
    assert "circle-open" in src
    assert "👀 OBSERWUJ " in ui
    assert "queue_paper" not in src
    assert "progress_paper" not in src
    assert "api_key" not in src


def test_real_plotly_watch_trace_is_visible_and_never_a_paper_arrow():
    import plotly.graph_objects as go
    for direction,side in ((1,"LONG"),(-1,"SHORT")):
        data=candles(direction)
        chart=go.Figure(go.Candlestick(
            x=data.index,open=data.Open,high=data.High,low=data.Low,close=data.Close))
        watches=annotate_watch_markers(chart,data,last_bars=30)
        assert watches and watches[-1]["side"]==side
        dot=[trace for trace in chart.data if "OBSERWUJ "+side in trace.name]
        assert len(dot)==1
        assert dot[0].mode=="markers"
        assert dot[0].marker.symbol=="circle-open"
        assert dot[0].x[-1]==data.index[-1]
        assert ("NIE PAPER" in dot[0].name)
        assert all(t.mode=="markers" for t in chart.data[1:])
        assert len(chart.data)>1
    short=go.Figure()
    assert annotate_watch_markers(short,data.iloc[:40])==[]
    assert len(short.data)==0
