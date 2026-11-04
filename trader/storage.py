"""Isolated PAPER event archive (no keys, no brokers, no live orders)."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent/'data'/'fokus_paper.sqlite3'

def connect(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True,exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10)
    con.execute('PRAGMA busy_timeout=10000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS signals (
      id TEXT PRIMARY KEY, recorded_utc TEXT NOT NULL, candle_utc TEXT NOT NULL,
      epic TEXT NOT NULL, source TEXT NOT NULL, timeframe TEXT NOT NULL,
      strategy TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
      entry REAL, stop REAL, target REAL, rr REAL, atr REAL,
      status TEXT NOT NULL DEFAULT 'PAPER_SIGNAL')''')
    con.execute('''CREATE TABLE IF NOT EXISTS paper_outcomes (
        signal_id TEXT PRIMARY KEY, status TEXT NOT NULL, pnl_pts REAL NOT NULL,
        reviewed_utc TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS scan_decisions (
       id TEXT PRIMARY KEY, recorded_utc TEXT NOT NULL, candle_utc TEXT NOT NULL,
       epic TEXT NOT NULL, source TEXT NOT NULL, timeframe TEXT NOT NULL,
       strategy TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL)''')
    con.commit()
    return con

def archive(con, event_id, candle_utc, epic, source, timeframe, result):
    if result.action not in ('LONG','SHORT'):
        # WAIT and rejected setups are not trades and must not affect win rate.
        cursor=con.execute('''INSERT OR IGNORE INTO scan_decisions
            (id,recorded_utc,candle_utc,epic,source,timeframe,strategy,action,reason)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (event_id,datetime.now(timezone.utc).isoformat(),candle_utc,epic,source,
             timeframe,result.strategy,result.action,result.reason))
        con.commit()
        return cursor.rowcount == 1
    cursor = con.execute('''INSERT OR IGNORE INTO signals
        (id,recorded_utc,candle_utc,epic,source,timeframe,strategy,action,reason,
         entry,stop,target,rr,atr) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (event_id,datetime.now(timezone.utc).isoformat(),candle_utc,epic,source,
         timeframe,result.strategy,result.action,result.reason,result.entry,
         result.stop,result.target,result.rr,result.atr))
    con.commit()
    return cursor.rowcount == 1

def recent(con,limit=100):
    con.row_factory=sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM signals WHERE action IN ('LONG','SHORT') ORDER BY recorded_utc DESC LIMIT ?",(limit,))]

def recent_scan_decisions(con,limit=100):
    """Separate WAIT/decision audit, never presented as completed trades."""
    con.row_factory=sqlite3.Row
    return [dict(r) for r in con.execute(
        'SELECT * FROM scan_decisions ORDER BY recorded_utc DESC LIMIT ?', (limit,))]


def audit_prior_paper_signals(con, closed_frame, epic, source, timeframe, spread, slippage=.25, holding=24):
    """Retrospective PAPER audit on subsequently closed bars, not broker fills."""
    from .strategy import simulate_outcome
    completed=[]
    signals=con.execute('''SELECT id,candle_utc,action,entry,stop,target FROM signals
      WHERE epic=? AND source=? AND timeframe=? AND action IN ('LONG','SHORT')
      AND id NOT IN (SELECT signal_id FROM paper_outcomes)''', (epic,source,timeframe)).fetchall()
    for signal_id, timestamp, side, entry, stop, target in signals:
        if entry is None or stop is None or target is None:
            continue
        t=datetime.fromisoformat(timestamp)
        if t.tzinfo is None:
            continue
        future=closed_frame[closed_frame.index > t].iloc[:holding]
        if len(future) < 1:
            continue
        result,pnl=simulate_outcome(future,side,float(entry),float(stop),float(target),spread,slippage)
        if result == 'PENDING' and len(future) == holding:
            exit_mid=float(future.iloc[-1].Close)
            first_mid=float(future.iloc[0].Open)
            if side=='LONG':
                pnl=(exit_mid-spread/2-slippage)-(first_mid+spread/2+slippage)
            else:
                pnl=(first_mid-spread/2-slippage)-(exit_mid+spread/2+slippage)
            result='TIMEOUT'
        if result=='PENDING':
            continue
        con.execute('''INSERT OR IGNORE INTO paper_outcomes
          (signal_id,status,pnl_pts,reviewed_utc) VALUES (?,?,?,?)''',
          (signal_id,result,round(float(pnl),2),datetime.now(timezone.utc).isoformat()))
        completed.append((signal_id,result,round(float(pnl),2)))
    con.commit()
    return completed

def paper_report(con):
    con.row_factory=sqlite3.Row
    return [dict(r) for r in con.execute('''SELECT s.candle_utc,s.epic,s.timeframe,s.strategy,
        s.action, o.status, o.pnl_pts, o.reviewed_utc
        FROM paper_outcomes o JOIN signals s ON o.signal_id=s.id
        ORDER BY o.reviewed_utc DESC LIMIT 300''')]
