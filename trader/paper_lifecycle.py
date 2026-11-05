"""Stateful PAPER lifecycle for Capital.com DEMO. NEVER place broker orders.

PENDING is a setup, not an opened trade. Entry uses NEXT closed bar OPEN
as a retrospective simulation (entry is not available to this close-only
scanner until that following bar closes). Mid SL/TP, fixed signal-time
spread, adverse slippage, conservative SL-first resolution, explicit gaps.
All state transitions + immutable events live in SQLite transactions.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import math
import sqlite3
import pandas as pd
from .market import PERIOD

ACTIVE = ("PENDING", "OPEN")
CLOSED = ("CLOSED_SL", "CLOSED_TP", "CLOSED_TIMEOUT", "INVALIDATED")
VERSION = "v3_paper_close_only"

def _utc(stamp):
    dt = pd.Timestamp(stamp)
    if dt.tzinfo is None:
        raise ValueError("PAPER wymaga timestampów UTC")
    return dt.tz_convert("UTC").isoformat()

def _event_id(trade_id, kind, at):
    return hashlib.sha256(f"{trade_id}|{kind}|{at}".encode()).hexdigest()

def ensure_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS paper_positions_v3 (
       trade_id TEXT PRIMARY KEY,
       epic TEXT NOT NULL, source TEXT NOT NULL, timeframe TEXT NOT NULL,
       strategy TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
       setup_utc TEXT NOT NULL, setup_reason TEXT NOT NULL,
       stop_mid REAL NOT NULL, target_mid REAL NOT NULL,
       setup_spread REAL NOT NULL, slippage REAL NOT NULL,
       status TEXT NOT NULL CHECK(status IN
           ('PENDING','OPEN','CLOSED_SL','CLOSED_TP','CLOSED_TIMEOUT','INVALIDATED')),
       opened_utc TEXT, closed_utc TEXT,
       entry_mid REAL, entry_executable REAL,
       exit_mid REAL, exit_executable REAL, pnl_pts REAL,
       bars_held INTEGER NOT NULL DEFAULT 0, close_reason TEXT NOT NULL DEFAULT '',
       model_version TEXT NOT NULL DEFAULT 'v3_paper_close_only',
       created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
    )""")
    # Forward-only migration: don't rewrite or erase historical PAPER v3 data.
    existing={r[1] for r in db.execute("PRAGMA table_info(paper_positions_v3)")}
    for column in ("entry_assumed_utc","entry_detected_utc"):
        if column not in existing:
            db.execute(f"ALTER TABLE paper_positions_v3 ADD COLUMN {column} TEXT")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_one_active
       ON paper_positions_v3(source,epic,timeframe)
       WHERE status IN ('PENDING','OPEN')""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_one_epic_active
       ON paper_positions_v3(source,epic)
       WHERE status IN ('PENDING','OPEN')""")
    db.execute("""CREATE TABLE IF NOT EXISTS paper_events_v3 (
       event_id TEXT PRIMARY KEY,trade_id TEXT NOT NULL,
       kind TEXT NOT NULL, candle_utc TEXT NOT NULL,
       reason TEXT NOT NULL, created_utc TEXT NOT NULL,
       FOREIGN KEY(trade_id) REFERENCES paper_positions_v3(trade_id)
    )""")
    db.commit()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _emit(db, tid, kind, when, reason):
    key=_event_id(tid,kind,when)
    db.execute("INSERT OR IGNORE INTO paper_events_v3 "
               "(event_id,trade_id,kind,candle_utc,reason,created_utc) "
               "VALUES (?,?,?,?,?,?)",(key,tid,kind,when,reason[:300],_now()))
    return key

def active_position(db, epic, source, timeframe):
    ensure_tables(db)
    db.row_factory=sqlite3.Row
    r=db.execute("""SELECT * FROM paper_positions_v3 WHERE
      epic=? AND source=? AND status IN ('PENDING','OPEN')
      ORDER BY created_utc ASC LIMIT 1""",(epic,source)).fetchone()
    return dict(r) if r else None

def recent_positions(db, limit=150):
    ensure_tables(db)
    db.row_factory=sqlite3.Row
    return [dict(x) for x in db.execute("""SELECT * FROM paper_positions_v3
            ORDER BY created_utc DESC LIMIT ?""",(max(1,min(1000,int(limit))),))]

def recent_events(db, limit=250):
    ensure_tables(db)
    db.row_factory=sqlite3.Row
    return [dict(x) for x in db.execute("""SELECT * FROM paper_events_v3
             ORDER BY created_utc DESC, rowid DESC LIMIT ?""",(max(1,min(2000,int(limit))),))]

def queue_paper(db, epic, source, timeframe, decision, signal_utc,
                spread, slippage=.25, market_status="TRADEABLE"):
    """One active demo-only position per instrument+source+TF; idempotent."""
    if source!="Capital.com DEMO REST" or market_status!="TRADEABLE":
        return None
    if timeframe not in PERIOD or decision.action not in ("LONG","SHORT"):
        return None
    try:
        values=[float(x) for x in
                (decision.entry,decision.stop,decision.target,spread,slippage)]
    except (TypeError,ValueError,OverflowError):
        return None
    if not all(math.isfinite(x) for x in values):
        return None
    entry,stop,target,spread,slippage=values
    if spread<0 or slippage<0:
        return None
    if not ((stop<entry<target) if decision.action=="LONG"
            else (target<entry<stop)):
        return None
    ensure_tables(db)
    stamp=_utc(signal_utc)
    tid=hashlib.sha256(f"{source}|{epic}|{timeframe}|{decision.strategy}|{stamp}|{decision.action}".encode()).hexdigest()
    now=_now()
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("SELECT trade_id FROM paper_positions_v3 WHERE trade_id=?",(tid,)).fetchone()
        active=db.execute("""SELECT trade_id FROM paper_positions_v3
             WHERE source=? AND epic=? AND status IN ('PENDING','OPEN')""",
             (source,epic)).fetchone()
        if old or active:
            db.commit()
            return None
        db.execute("""INSERT INTO paper_positions_v3
            (trade_id,epic,source,timeframe,strategy,side,setup_utc,setup_reason,
            stop_mid,target_mid,setup_spread,slippage,status,created_utc,updated_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid,epic,source,timeframe,decision.strategy,decision.action,
             stamp,str(decision.reason)[:300],float(decision.stop),
             float(decision.target),float(spread),float(slippage),'PENDING',now,now))
        _emit(db,tid,decision.action+"_SETUP",stamp,decision.reason)
        db.commit()
        return tid
    except BaseException:
        db.rollback()
        raise

def _close(db, pos, state, candle, reason, exit_mid=None, exit_exec=None,pnl=None):
    stamp=_utc(candle)
    db.execute("""UPDATE paper_positions_v3 SET status=?,closed_utc=?,exit_mid=?,
      exit_executable=?,pnl_pts=?,close_reason=?,updated_utc=? WHERE trade_id=?""",
      (state,stamp,exit_mid,exit_exec,pnl,reason[:300],_now(),pos["trade_id"]))
    suffix={"CLOSED_SL":"PAPER_CLOSE_SL","CLOSED_TP":"PAPER_CLOSE_TP",
            "CLOSED_TIMEOUT":"PAPER_TIMEOUT","INVALIDATED":"PAPER_INVALIDATED"}[state]
    _emit(db,pos["trade_id"],suffix,stamp,reason)

def progress_paper(db, frame, epic, source, timeframe, max_holding=20):
    """Consume only consecutive CLOSED candles. Crash-safe and idempotent.

    If next-bar entry was missed or any candle is absent, invalidate rather
    than backfill an impossible fill. A reopened position is restored from DB.
    """
    if source!="Capital.com DEMO REST" or timeframe not in PERIOD:
        return []
    if frame is None or frame.empty:
        return []
    if frame.index.tz is None or not frame.index.is_monotonic_increasing:
        raise ValueError("Tylko rosnące zamknięte świece UTC")
    if max_holding<2 or max_holding>300:
        raise ValueError("Nieprawidłowy horyzont PAPER")
    ensure_tables(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.row_factory=sqlite3.Row
        raw=db.execute("""SELECT * FROM paper_positions_v3
            WHERE source=? AND epic=? AND timeframe=? AND status IN ('PENDING','OPEN')""",
            (source,epic,timeframe)).fetchone()
        if not raw:
            db.commit()
            return []
        pos=dict(raw)
        tid=pos["trade_id"]
        step=pd.Timedelta(seconds=PERIOD[timeframe])
        t_setup=pd.Timestamp(pos["setup_utc"])
        closed=frame[frame.index>t_setup]
        events=[]
        if closed.empty:
            db.commit()
            return events
        expected=t_setup+step
        if pos["status"]=="PENDING":
            first=closed.iloc[0]
            first_t=closed.index[0]
            if first_t!=expected:
                _close(db,pos,"INVALIDATED",first_t,"Brak dokładnie następnej zamkniętej świecy; brak wiarygodnego wejścia.")
                events.append("PAPER_INVALIDATED")
                db.commit()
                return events
            open_mid=float(first.Open)
            stop,target=float(pos["stop_mid"]),float(pos["target_mid"])
            if not ((stop<open_mid<target) if pos["side"]=="LONG"
                    else (target<open_mid<stop)):
                _close(db,pos,"INVALIDATED",first_t,"Luka cenowa poza SL/TP; symulowane wejście pominięte.")
                events.append("PAPER_INVALIDATED")
                db.commit()
                return events
            half=float(pos["setup_spread"])/2
            slip=float(pos["slippage"])
            filled=(open_mid+half+slip if pos["side"]=="LONG"
                    else open_mid-half-slip)
            # On a CLOSE-time index, the next bar opens at t_setup, but
            # this OPEN price is observed only when the bar closes at first_t.
            # Never present the reconstructed OPEN as a real-time executable quote.
            assumed_open_utc=_utc(t_setup)
            recognized_utc=_now()
            db.execute("""UPDATE paper_positions_v3 SET status='OPEN',opened_utc=?,
                entry_mid=?,entry_executable=?,entry_assumed_utc=?,
                entry_detected_utc=?,updated_utc=? WHERE trade_id=?""",
                (_utc(first_t),open_mid,filled,assumed_open_utc,
                 recognized_utc,recognized_utc,tid))
            pos.update(status="OPEN",opened_utc=_utc(first_t),
                       entry_mid=open_mid,entry_executable=filled,
                       entry_assumed_utc=assumed_open_utc,
                       entry_detected_utc=recognized_utc)
            _emit(db,tid,"PAPER_OPEN",_utc(first_t),
                  "Retrospektywny OPEN MID następnej świecy; wykryty dopiero po jej zamknięciu.")
            events.append("PAPER_OPEN")
            loop=closed
            prev=t_setup
            bars_held=0
        else:
            prev=pd.Timestamp(pos["opened_utc"])+step*(int(pos["bars_held"])-1)
            if int(pos["bars_held"])<1:
                # A preexisting OPEN trade must have >=1 evaluated candle.
                _close(db,pos,"INVALIDATED",closed.index[0],"Niespójny stan PAPER OPEN bez barów.")
                events.append("PAPER_INVALIDATED")
                db.commit()
                return events
            loop=frame[frame.index>prev]
            bars_held=int(pos["bars_held"])
        if loop.empty:
            db.commit()
            return events
        half=float(pos["setup_spread"])/2
        slip=float(pos["slippage"])
        for stamp,row in loop.iterrows():
            if stamp!=prev+step:
                _close(db,pos,"INVALIDATED",stamp,"Luka w świecach zamkniętych; nie zgaduję P&L.")
                events.append("PAPER_INVALIDATED")
                break
            if pos["side"]=="LONG":
                hit_stop=float(row.Low)<=float(pos["stop_mid"])
                hit_target=float(row.High)>=float(pos["target_mid"])
            else:
                hit_stop=float(row.High)>=float(pos["stop_mid"])
                hit_target=float(row.Low)<=float(pos["target_mid"])
            bars_held+=1
            if hit_stop or hit_target:
                if hit_stop:
                    state="CLOSED_SL"
                    exit_mid=(min(float(pos["stop_mid"]),float(row.Open))
                              if pos["side"]=="LONG" else
                              max(float(pos["stop_mid"]),float(row.Open)))
                    reason="SL PAPER: konserwatywnie przed TP, jeśli oba dotknięte."
                else:
                    state="CLOSED_TP"
                    exit_mid=float(pos["target_mid"])
                    reason="TP PAPER: cena MID dotknęła celu."
                exit_ex=(exit_mid-half-slip if pos["side"]=="LONG"
                         else exit_mid+half+slip)
                pnl=(exit_ex-float(pos["entry_executable"]) if pos["side"]=="LONG"
                     else float(pos["entry_executable"])-exit_ex)
                _close(db,pos,state,stamp,reason,exit_mid,exit_ex,round(pnl,2))
                events.append("PAPER_CLOSE_SL" if hit_stop else "PAPER_CLOSE_TP")
                break
            if bars_held>=max_holding:
                exit_mid=float(row.Close)
                exit_ex=(exit_mid-half-slip if pos["side"]=="LONG"
                         else exit_mid+half+slip)
                pnl=(exit_ex-float(pos["entry_executable"]) if pos["side"]=="LONG"
                     else float(pos["entry_executable"])-exit_ex)
                _close(db,pos,"CLOSED_TIMEOUT",stamp,
                       "Limit czasu PAPER bez SL/TP.",exit_mid,exit_ex,round(pnl,2))
                events.append("PAPER_TIMEOUT")
                break
            prev=stamp
            db.execute("""UPDATE paper_positions_v3 SET bars_held=?,updated_utc=?
                   WHERE trade_id=?""",(bars_held,_now(),tid))
        if events and events[-1] in ("PAPER_CLOSE_SL","PAPER_CLOSE_TP","PAPER_TIMEOUT"):
            db.execute("UPDATE paper_positions_v3 SET bars_held=? WHERE trade_id=?",
                       (bars_held,tid))
        db.commit()
        return events
    except BaseException:
        db.rollback()
        raise
