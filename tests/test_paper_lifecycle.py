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
    assert pd.Timestamp(live["entry_assumed_utc"])==T0
    assert pd.Timestamp(live["opened_utc"])==T0+pd.Timedelta(minutes=1)
    assert pd.Timestamp(live["entry_detected_utc"]).tzinfo is not None
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


def test_global_one_open_position_across_timeframes(tmp_path):
    db=connect(tmp_path/"global.sqlite3")
    ensure_tables(db)
    first=queue_paper(db,"US500",SRC,"MINUTE",decision(),T0,.6,slippage=0)
    assert first
    second=queue_paper(db,"US500",SRC,"MINUTE_5",
        Decision("SHORT","EMA TREND","another TF",100,102,98),
        T0,.6,slippage=0)
    assert second is None
    assert active_position(db,"US500",SRC,"MINUTE_5")["trade_id"]==first


def test_bad_setup_geometry_or_finite_prevent_pending(tmp_path):
    db=connect(tmp_path/"geometry.sqlite3")
    ensure_tables(db)
    for d in (
        Decision("LONG","EMA TREND","no entry",None,98,102),
        Decision("LONG","EMA TREND","wrong stop",100,102,103),
        Decision("SHORT","EMA TREND","wrong stop",100,98,99),
        Decision("LONG","EMA TREND","infinite",float("inf"),98,102),
    ):
        assert queue_paper(db,"US500",SRC,"MINUTE",d,T0,.6) is None
    assert recent_positions(db)==[]


def test_forward_migration_preserves_existing_position(tmp_path):
    db=connect(tmp_path/"migration.sqlite3")
    db.execute("""CREATE TABLE paper_positions_v3 (
       trade_id TEXT PRIMARY KEY, epic TEXT NOT NULL,
       source TEXT NOT NULL, timeframe TEXT NOT NULL, strategy TEXT NOT NULL,
       side TEXT NOT NULL,setup_utc TEXT NOT NULL,setup_reason TEXT NOT NULL,
       stop_mid REAL NOT NULL,target_mid REAL NOT NULL,
       setup_spread REAL NOT NULL,slippage REAL NOT NULL,status TEXT NOT NULL,
       opened_utc TEXT,closed_utc TEXT,entry_mid REAL,entry_executable REAL,
       exit_mid REAL,exit_executable REAL,pnl_pts REAL,
       bars_held INTEGER NOT NULL DEFAULT 0, close_reason TEXT DEFAULT '',
       model_version TEXT DEFAULT 'v3_paper_close_only',
       created_utc TEXT NOT NULL,updated_utc TEXT NOT NULL)""")
    db.execute("""INSERT INTO paper_positions_v3
       (trade_id,epic,source,timeframe,strategy,side,setup_utc,setup_reason,
       stop_mid,target_mid,setup_spread,slippage,status,created_utc,updated_utc)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       ('old','US500',SRC,'MINUTE','EMA TREND','LONG',T0.isoformat(),
        'historical',98,102,.6,.25,'PENDING',T0.isoformat(),T0.isoformat()))
    db.commit()
    ensure_tables(db)
    assert active_position(db,'US500',SRC,'MINUTE')['trade_id']=='old'
    cols={r[1] for r in db.execute("PRAGMA table_info(paper_positions_v3)")}
    assert {'entry_assumed_utc','entry_detected_utc'}.issubset(cols)
    ensure_tables(db)
    assert len(recent_positions(db))==1
