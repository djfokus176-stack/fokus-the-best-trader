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
    # In-place forward-only migration; never delete old PAPER rows.
    signal_columns={row[1] for row in con.execute('PRAGMA table_info(signals)')}
    if 'entry_spread' not in signal_columns:
        con.execute('ALTER TABLE signals ADD COLUMN entry_spread REAL')
    outcome_columns={row[1] for row in con.execute('PRAGMA table_info(paper_outcomes)')}
    if 'model_version' not in outcome_columns:
        con.execute("ALTER TABLE paper_outcomes ADD COLUMN model_version TEXT NOT NULL DEFAULT 'legacy_v1'")
    con.execute('''CREATE TABLE IF NOT EXISTS candle_history (
        source TEXT NOT NULL, epic TEXT NOT NULL, timeframe TEXT NOT NULL,
        candle_utc TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
        low REAL NOT NULL, close REAL NOT NULL, spread REAL NOT NULL,
        PRIMARY KEY(source,epic,timeframe,candle_utc))''')
    con.commit()
    return con

def archive(con, event_id, candle_utc, epic, source, timeframe, result, spread=None):
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
         entry,stop,target,rr,atr,entry_spread) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (event_id,datetime.now(timezone.utc).isoformat(),candle_utc,epic,source,
         timeframe,result.strategy,result.action,result.reason,result.entry,
         result.stop,result.target,result.rr,result.atr,spread))
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
    signals=con.execute('''SELECT id,candle_utc,action,entry,stop,target,entry_spread FROM signals
      WHERE epic=? AND source=? AND timeframe=? AND action IN ('LONG','SHORT')
      AND entry_spread IS NOT NULL
      AND id NOT IN (SELECT signal_id FROM paper_outcomes)''', (epic,source,timeframe)).fetchall()
    for signal_id, timestamp, side, entry, stop, target, entry_spread in signals:
        if entry is None or stop is None or target is None:
            continue
        t=datetime.fromisoformat(timestamp)
        if t.tzinfo is None:
            continue
        future=closed_frame[closed_frame.index > t].iloc[:holding]
        if len(future) < 1:
            continue
        signal_spread=float(entry_spread)
        result,pnl=simulate_outcome(future,side,float(entry),float(stop),float(target),signal_spread,slippage)
        if result == 'PENDING' and len(future) == holding:
            exit_mid=float(future.iloc[-1].Close)
            first_mid=float(future.iloc[0].Open)
            if side=='LONG':
                pnl=(exit_mid-signal_spread/2-slippage)-(first_mid+signal_spread/2+slippage)
            else:
                pnl=(first_mid-signal_spread/2-slippage)-(exit_mid+signal_spread/2+slippage)
            result='TIMEOUT'
        if result=='PENDING':
            continue
        con.execute('''INSERT OR IGNORE INTO paper_outcomes
          (signal_id,status,pnl_pts,reviewed_utc,model_version) VALUES (?,?,?,?,?)''',
          (signal_id,result,round(float(pnl),2),datetime.now(timezone.utc).isoformat(),
           'v2_mid_bidask'))
        completed.append((signal_id,result,round(float(pnl),2)))
    con.commit()
    return completed

def paper_report(con):
    con.row_factory=sqlite3.Row
    return [dict(r) for r in con.execute('''SELECT s.candle_utc,s.epic,s.timeframe,s.strategy,
        s.action, o.status, o.pnl_pts, o.reviewed_utc, o.model_version, s.entry_spread
        FROM paper_outcomes o JOIN signals s ON o.signal_id=s.id
        WHERE o.model_version='v2_mid_bidask'
        ORDER BY o.reviewed_utc DESC LIMIT 300''')]


def legacy_outcomes_count(con):
    """Old results kept for forensic review, excluded from v2 performance metrics."""
    return int(con.execute(
        "SELECT COUNT(*) FROM paper_outcomes WHERE model_version!='v2_mid_bidask'").fetchone()[0])


def archive_candles(con, frame, epic: str, source: str, timeframe: str) -> int:
    """Deduplicate only CLOSED API bars; separated by instrument and feed."""
    import pandas as pd
    if frame is None or frame.empty or source not in (
        'Capital.com DEMO REST','Capital.com LIVE REST'):
        return 0
    if frame.index.tz is None:
        raise ValueError('Świece muszą mieć UTC timezone.')
    required={'Open','High','Low','Close','Spread'}
    if not required.issubset(frame.columns):
        raise ValueError('Niekompletne OHLC/Spread.')
    rows=[]
    for stamp,row in frame.iterrows():
        if row[list(required)].isna().any():
            continue
        rows.append((source,epic,timeframe,stamp.isoformat(),
            float(row.Open),float(row.High),float(row.Low),
            float(row.Close),float(row.Spread)))
    before=con.total_changes
    con.executemany('''INSERT OR IGNORE INTO candle_history
      (source,epic,timeframe,candle_utc,open,high,low,close,spread)
      VALUES (?,?,?,?,?,?,?,?,?)''',rows)
    con.commit()
    return con.total_changes-before


def load_candles(con, epic: str, source: str, timeframe: str, limit=20000):
    """Read only the requested exact feed. Empty means no retained history."""
    import pandas as pd
    rows=con.execute('''SELECT candle_utc,open,high,low,close,spread
      FROM candle_history WHERE epic=? AND source=? AND timeframe=?
      ORDER BY candle_utc DESC LIMIT ?''',
      (epic,source,timeframe,min(int(limit),100000))).fetchall()
    if not rows:return pd.DataFrame()
    df=pd.DataFrame(rows,columns=['Time','Open','High','Low','Close','Spread'])
    df['Time']=pd.to_datetime(df.Time,utc=True)
    return df.set_index('Time').sort_index()
