"""PAPER lifecycle unit tests: next-closed-bar entry, SL-first, cost, idempotency."""
import sqlite3
import pandas as pd
from trader.paper_lifecycle import (
    ensure_tables, queue_paper, progress_paper, active_position, recent_positions,
    recent_events)
from trader.strategy import Decision
from trader.storage import connect


T0=pd.Timestamp("2026-11-05T13:00:00Z")
SRC="Capital.com DEMO REST"
def candles(rows):
    ts=pd.date_range(T0+pd.Timedelta(minutes=1),periods=len(rows),freq="min",tz="UTC")
    return pd.DataFrame(rows,index=ts,columns=["Open","High","Low","Close"])

def decision(side="LONG"):
    if side=="LONG":
        return Decision("LONG","EMA TREND","PAPER candidate",100,98,102,2.0)
    return Decision("SHORT","EMA TREND","PAPER candidate",100,102,98,2.0)

def setup(tmp_path,side="LONG",slippage=0):
    db=connect(tmp_path/"v3.sqlite3")
    ensure_tables(db)
    tid=queue_paper(db,"US500",SRC,"MINUTE",decision(side),T0,.6,slippage)
    assert tid
    return db,tid

def test_long_waits_for_next_closed_bar_and_then_tp(tmp_path):
    db,tid=setup(tmp_path)
    assert active_position(db,"US500",SRC,"MINUTE")["status"]=="PENDING"
    assert progress_paper(db,pd.DataFrame(),"US500",SRC,"MINUTE")==[]
    # First next closed bar touches neither SL nor TP -> trade OPEN.
    b1=candles([[100,101,99,100.8]])
    assert progress_paper(db,b1,"US500",SRC,"MINUTE")==["PAPER_OPEN"]
    assert progress_paper(db,b1,"US500",SRC,"MINUTE")==[]
    live=active_position(db,"US500",SRC,"MINUTE")
    assert live["entry_executable"]==100.3
    # Subsequent TP.
    b2=candles([[100,101,99,100.8],[100.8,102.3,100.5,102.1]])
    assert progress_paper(db,b2,"US500",SRC,"MINUTE")==["PAPER_CLOSE_TP"]
    assert active_position(db,"US500",SRC,"MINUTE") is None
    pos=recent_positions(db)[0]
    assert pos["status"]=="CLOSED_TP" and pos["pnl_pts"]==1.4
    kinds=[e["kind"] for e in recent_events(db)]
    assert kinds.count("PAPER_OPEN")==1 and kinds.count("PAPER_CLOSE_TP")==1
    assert len(kinds)==3
    assert progress_paper(db,b2,"US500",SRC,"MINUTE")==[]


def test_intrabar_stop_priority_both_sides(tmp_path):
    for side in ("LONG","SHORT"):
        db,tid=setup(tmp_path,side)
        bar=candles([[100,103,97,100]])
        events=progress_paper(db,bar,"US500",SRC,"MINUTE")
        assert events==["PAPER_OPEN","PAPER_CLOSE_SL"]
        row=recent_positions(db)[0]
        assert row["status"]=="CLOSED_SL"
        assert row["pnl_pts"]==-2.6
        db.close()
        # Same sqlite path reused but status closed; next side different ID.
        # side-specific signal hash changes, so no collision.


def test_cannot_open_two_positions_on_same_tf(tmp_path):
    db,tid=setup(tmp_path)
    second=queue_paper(db,"US500",SRC,"MINUTE",
                       Decision("SHORT","DRUGA FALA","other",100,102,98),
                       T0,.6)
    assert second is None
    assert len(recent_positions(db))==1
    assert queue_paper(db,"US500",SRC,"MINUTE",decision(),T0,.6) is None


def test_missed_candle_or_entry_gap_marks_invalidated_not_profit(tmp_path):
    db,tid=setup(tmp_path)
    bars=candles([[100,101,99,100],[100,101,99,100]])
    bars=bars.iloc[1:]
    assert progress_paper(db,bars,"US500",SRC,"MINUTE")==["PAPER_INVALIDATED"]
    assert recent_positions(db)[0]["pnl_pts"] is None
    db.close()
    db,tid=setup(tmp_path,side="SHORT")
    assert progress_paper(db,candles([[103,104,102,103]]),"US500",SRC,"MINUTE")==["PAPER_INVALIDATED"]
    assert recent_positions(db)[0]["status"]=="INVALIDATED"


def test_short_tp_net_and_timeout(tmp_path):
    db,tid=setup(tmp_path,side="SHORT",slippage=.25)
    assert progress_paper(db,candles([[100,100.5,97.8,98.1]]),"US500",SRC,"MINUTE")==["PAPER_OPEN","PAPER_CLOSE_TP"]
    pos=recent_positions(db)[0]
    assert pos["pnl_pts"]==.9
    db.close()
    db,tid=setup(tmp_path,side="LONG",slippage=0)
    bars=candles([[100,100.5,99.5,100],[100,100.5,99.5,100.2]])
    assert progress_paper(db,bars,"US500",SRC,"MINUTE",max_holding=2)==["PAPER_OPEN","PAPER_TIMEOUT"]
    pos=recent_positions(db)[0]
    assert pos["status"]=="CLOSED_TIMEOUT" and pos["pnl_pts"]==-.4


def test_db_reopens_with_position_and_no_duplicate_events(tmp_path):
    db,tid=setup(tmp_path)
    b=candles([[100,101,99,100]])
    assert progress_paper(db,b,"US500",SRC,"MINUTE")==["PAPER_OPEN"]
    db.close()
    db=connect(tmp_path/"v3.sqlite3")
    b2=candles([[100,101,99,100],[100,102.2,99,102]])
    assert progress_paper(db,b2,"US500",SRC,"MINUTE")==["PAPER_CLOSE_TP"]
    assert len(recent_events(db))==3


def test_read_only_security_ignores_live_or_csv(tmp_path):
    db=connect(tmp_path/"v3.sqlite3")
    ensure_tables(db)
    for src in ("Capital.com LIVE REST","CSV NAUKA (NIE LIVE)"):
        assert queue_paper(db,"US500",src,"MINUTE",decision(),T0,.6) is None
        assert progress_paper(db,candles([[100,102,99,101]]),"US500",src,"MINUTE")==[]
    assert queue_paper(db,"US500",SRC,"MINUTE",decision(),T0,.6,market_status="CLOSED") is None


def test_concurrent_partial_index_refuses_extra_active(tmp_path):
    db=connect(tmp_path/"v3.sqlite3")
    ensure_tables(db)
    idx=db.execute("SELECT name FROM sqlite_master WHERE name='uq_paper_one_active'").fetchone()
    assert idx is not None
