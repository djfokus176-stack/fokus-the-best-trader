"""Daily simulated PAPER drawdown brake is causal, day-scoped and never an order."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from trader.market import Snapshot
from trader.paper_daily_risk import paper_daily_risk
from trader.paper_lifecycle import ensure_tables,recent_positions
from trader.strategy import Decision
import trader.worker as worker


SRC="Capital.com DEMO REST"


def db_fixture():
    db=sqlite3.connect(":memory:")
    ensure_tables(db)
    return db


def closed(db, ident, when, pnl, *, epic="US500", source=SRC,
           status="CLOSED_SL"):
    db.execute("""INSERT INTO paper_positions_v3
      (trade_id,epic,source,timeframe,strategy,side,setup_utc,
       setup_reason,stop_mid,target_mid,setup_spread,slippage,status,
       created_utc,updated_utc,closed_utc,pnl_pts)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ident,epic,source,"MINUTE","EMA TREND","LONG",when,
       "controlled synthetic fixture",98.,104.,.6,.25,status,
       when,when,when,float(pnl)))
    db.commit()


def test_daily_drawdown_uses_only_closed_known_trades_and_latches():
    db=db_fixture()
    closed(db,"one","2026-11-11T08:00:00+00:00",-7.)
    closed(db,"two","2026-11-11T09:00:00+00:00",-14.)
    # Future close must not leak into an earlier scan's risk status.
    closed(db,"later","2026-11-11T12:00:00+00:00",+15.)
    closed(db,"another-source","2026-11-11T08:00:00+00:00",-100.,
           source="Capital.com LIVE REST")
    closed(db,"another-market","2026-11-11T08:00:00+00:00",-100.,
           epic="NAS100")
    closed(db,"still-open","2026-11-11T08:00:00+00:00",-100.,
           status="OPEN")
    first=paper_daily_risk(db,epic="US500",source=SRC,
                           asof="2026-11-11T10:00:00Z",max_drawdown_pts=20)
    assert first.day=="2026-11-11"
    assert first.closed_count==2
    assert first.realized_pts==-21
    assert first.max_drawdown_pts==21
    assert first.blocked
    # Even after an existing OPEN has later closed profitably the brake
    # remains latched for the rest of the Warsaw calendar date.
    after=paper_daily_risk(db,epic="US500",source=SRC,
                           asof="2026-11-11T13:00:00Z",max_drawdown_pts=20)
    assert after.closed_count==3 and after.realized_pts==-6
    assert after.max_drawdown_pts==21 and after.blocked
    assert paper_daily_risk(db,epic="US500",source=SRC,
                           asof="2026-11-12T08:00:00Z",
                           max_drawdown_pts=20).blocked is False


def test_drawdown_from_intraday_high_not_only_negative_daily_pnl():
    db=db_fixture()
    closed(db,"gain","2026-11-11T08:00:00+00:00",+12.)
    closed(db,"loss","2026-11-11T08:20:00+00:00",-20.)
    r=paper_daily_risk(db,epic="US500",source=SRC,
                       asof="2026-11-11T08:30:00+00:00",max_drawdown_pts=20)
    assert r.realized_pts==-8
    assert r.max_drawdown_pts==20
    assert r.blocked is True


def test_warsaw_midnight_and_daylight_saving_are_respected():
    db=db_fixture()
    closed(db,"winter","2026-11-10T23:30:00+00:00",-21.)
    x=paper_daily_risk(db,epic="US500",source=SRC,
                       asof="2026-11-11T00:30:00+00:00")
    assert x.day=="2026-11-11" and x.blocked
    # Earlier UTC November 10 at 22:30 is still November 10 in Warsaw.
    y=paper_daily_risk(db,epic="US500",source=SRC,
                       asof="2026-11-10T22:30:00+00:00")
    assert y.day=="2026-11-10" and not y.blocked
    closed(db,"summer","2026-07-12T22:30:00+00:00",-22.)
    summer=paper_daily_risk(db,epic="US500",source=SRC,
                            asof="2026-07-13T00:30:00+00:00")
    assert summer.day=="2026-07-13" and summer.blocked


def test_zero_explicitly_disables_daily_brake_and_bad_config_fails_closed():
    db=db_fixture()
    closed(db,"one","2026-11-11T08:00:00+00:00",-30.)
    r=paper_daily_risk(db,epic="US500",source=SRC,
                       asof="2026-11-11T10:00:00Z",max_drawdown_pts=0)
    assert r.max_drawdown_pts==30
    assert not r.blocked
    for limit in (-1,float("nan"),float("inf")):
        with pytest.raises(ValueError):
            paper_daily_risk(db,epic="US500",source=SRC,
                             asof="2026-11-11T10:00:00Z",
                             max_drawdown_pts=limit)
    with pytest.raises(ValueError):
        paper_daily_risk(db,epic="US500",source=SRC,
                         asof="2026-11-11T10:00:00",max_drawdown_pts=20)


def test_worker_blocks_new_paper_only_and_keeps_ledger_unchanged(monkeypatch):
    db=db_fixture()
    # Deterministic day: do not make the test dependent on midnight Warsaw.
    at=pd.Timestamp("2026-11-11T12:00:00Z")
    # A dated close in Warsaw's today, already known by the current scan.
    older=at-pd.Timedelta(minutes=11)
    closed(db,"prior-loss",older.isoformat(),-22.)
    idx=pd.date_range(end=at,periods=155,freq="min",tz="UTC")
    data=pd.DataFrame({"Open":np.full(155,100.),
        "High":np.full(155,101.),
        "Low":np.full(155,99.),
        "Close":np.full(155,100.),
        "Spread":np.full(155,.6)},index=idx)
    snap=Snapshot(data,SRC,"US500","MINUTE",.6,
                  at.to_pydatetime(),90,True,"synthetic",quote_spread=.6)
    class Demo:
        environment="DEMO"
        def market_state(self,epic): return "TRADEABLE"
    monkeypatch.setattr(worker,"fetch_all_timeframes",
                        lambda *a,**kw:({"MINUTE":snap},{}))
    monkeypatch.setattr(worker,"archive_candles",lambda *a,**kw:0)
    monkeypatch.setattr(worker,"current_feed_status",lambda *a:(True,"OK",0))
    monkeypatch.setattr(worker,"decide_any",
                        lambda *a,**kw:Decision("LONG","EMA TREND",
                                                 "synthetic",100,98,104,1.6))
    ready=SimpleNamespace(ready=True,reason="OK",timeframe="MINUTE")
    monkeypatch.setattr(worker,"filter_mtf_decision",
                        lambda *a,**kw:(
                            Decision("LONG","EMA TREND","synthetic",100,98,104,1.6),
                            [ready]*4))
    monkeypatch.setenv("FOKUS_PAPER_DAILY_STOP_PTS","20")
    result=worker.scan_once(Demo(),"US500","MINUTE","EMA TREND",2,
                            db,strict_macro=False)
    assert "PAPER_DAILY_DRAWDOWN_LIMIT" in result
    assert "QUEUE=NO" in result and "NEW_PAPER_PAUSED_ONLY" in result
    assert len(recent_positions(db))==1
    assert recent_positions(db)[0]["status"]=="CLOSED_SL"
    # After deliberately disabling this PAPER-only brake, same clean
    # synthetic setup is once again permitted. Not a production recommendation.
    monkeypatch.setenv("FOKUS_PAPER_DAILY_STOP_PTS","0")
    unblocked=worker.scan_once(Demo(),"US500","MINUTE","EMA TREND",
                               2,db,strict_macro=False)
    assert "QUEUE=YES" in unblocked
    assert len(recent_positions(db))==2
