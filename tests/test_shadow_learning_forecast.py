"""Regression tests for leakage-free self-learning; no real broker requests."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import sqlite3
import pandas as pd

from trader.forecast_audit import update_forecast, forecast_metrics
from trader.paper_learning import strategy_scorecard
from trader.paper_lifecycle import ensure_tables


def snap(start, n=7, tf="MINUTE", values=None):
    dates=pd.date_range(start=start,periods=n,freq="min",tz="UTC")
    if values is None:
        values=[100.+i*.3 for i in range(n)]
    return SimpleNamespace(good=True,epic="US500",source="Capital.com DEMO REST",
        resolution=tf,confirmed_utc=dates[-1].to_pydatetime(),
        frame=pd.DataFrame({"Close":values[:n]},index=dates))


def test_forecast_is_created_before_next_candle_and_scored_once():
    initial=update_forecast({},snap("2026-11-09 12:00",n=6))
    assert initial["pending"]["at_utc"]=="2026-11-09T12:05:00+00:00"
    assert initial["resolved"]==[]
    assert initial["pending"]["model"]=="NAIVE"
    repeat=update_forecast(initial,snap("2026-11-09 12:00",n=6))
    assert repeat==initial
    verified=update_forecast(initial,snap("2026-11-09 12:00",n=7))
    assert len(verified["resolved"])==1
    assert verified["resolved"][0]["target_utc"]=="2026-11-09T12:06:00+00:00"
    assert verified["resolved"][0]["actual"]==101.8
    assert forecast_metrics(verified)["observations"]==1
    assert update_forecast(verified,snap("2026-11-09 12:00",n=7))==verified


def test_delayed_scan_scores_only_exact_next_closed_bar():
    initial=update_forecast({},snap("2026-11-09 12:00",n=6))
    # GitHub may scan 6 minutes later, but the next CLOSED bar remains
    # available in the broker's historical response.
    delayed=update_forecast(initial,snap("2026-11-09 12:00",n=12))
    assert len(delayed["resolved"])==1
    assert delayed["resolved"][0]["target_utc"]=="2026-11-09T12:06:00+00:00"
    assert delayed["resolved"][0]["actual"]==101.8
    assert delayed["pending"]["at_utc"]=="2026-11-09T12:11:00+00:00"
    # If the exact target bar is absent from history, do NOT interpolate.
    missing=snap("2026-11-09 12:00",n=12)
    missing.frame=missing.frame.drop(pd.Timestamp("2026-11-09 12:06",tz="UTC"))
    expired=update_forecast(initial,missing)
    assert len(expired["resolved"])==0
    assert expired["missed_candles"]==1


def test_forecast_does_not_score_missing_candle_or_bad_source():
    a=update_forecast({},snap("2026-11-09 12:00",n=6))
    bad=snap("2026-11-09 12:00",n=7)
    bad.good=False
    assert update_forecast(a,bad)==a
    missing=snap("2026-11-09 12:04",n=7)
    missing.frame=missing.frame.drop(pd.Timestamp("2026-11-09 12:06",tz="UTC"))
    gap=update_forecast(a,missing)
    assert gap["missed_candles"]==1
    assert len(gap["resolved"])==0


def test_model_selection_uses_prior_scored_errors_only():
    # In long-run OOS, historical errors can favor MOMENTUM.
    from trader.forecast_audit import _select
    past=[{"errors":{"NAIVE":1.0,"MOMENTUM":0.1,"MEAN_REVERSION":2.0}}
          for _ in range(35)]
    assert _select(past)=="MOMENTUM"
    assert _select(past[:29])=="NAIVE"


def insert(db, i, pnl, strategy="EMA TREND", policy="fixed", status="CLOSED_TP"):
    t=(datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(minutes=i)).isoformat()
    db.execute("""INSERT INTO paper_positions_v3
        (trade_id,epic,source,timeframe,strategy,side,
         setup_utc,setup_reason,stop_mid,target_mid,setup_spread,slippage,
         status,closed_utc,pnl_pts,created_utc,updated_utc,exit_policy)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (str(i),"US500","Capital.com DEMO REST","MINUTE",strategy,"LONG",
        t,"TEST",95.0,110.0,0.5,0.25,status,t,pnl,t,t,policy))


def test_closed_paper_learning_separates_holdout_policies_and_wait():
    db=sqlite3.connect(":memory:")
    ensure_tables(db)
    for i in range(120):
        insert(db,i,1.0 if i<84 else -2.0)
    insert(db,121,None,status="OPEN")
    insert(db,122,3.0,policy="adaptive")
    report=strategy_scorecard(db)
    assert report["closed_positions"]==121
    fixed=next(x for x in report["strategies"] if x["exit_policy"]=="fixed")
    adaptive=next(x for x in report["strategies"] if x["exit_policy"]=="adaptive")
    assert fixed["total"]==120
    assert fixed["train"]["n"]==84
    assert fixed["holdout"]["n"]==36
    assert fixed["holdout"]["sum_pts"]==-72.0
    assert fixed["shadow_priority"]=="INSUFFICIENT_EVIDENCE"
    assert fixed["live_edge_proven"] is False
    assert adaptive["holdout"]["n"]==0
    assert adaptive["total"]==1


def test_no_closed_positions_is_not_a_proven_edge():
    db=sqlite3.connect(":memory:")
    assert strategy_scorecard(db)["strategies"]==[]
