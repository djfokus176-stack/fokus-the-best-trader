"""Old PAPER outcomes are retained but never included in post-fix performance."""
import sqlite3
import pandas as pd
from trader.storage import (connect,archive,audit_prior_paper_signals,
                            paper_report,legacy_outcomes_count,recent)
from trader.strategy import Decision


def test_legacy_schema_migration_is_non_destructive(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    con=sqlite3.connect(path)
    con.execute("""CREATE TABLE signals (
      id TEXT PRIMARY KEY, recorded_utc TEXT NOT NULL, candle_utc TEXT NOT NULL,
      epic TEXT NOT NULL, source TEXT NOT NULL, timeframe TEXT NOT NULL,
      strategy TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
      entry REAL, stop REAL, target REAL, rr REAL, atr REAL,
      status TEXT NOT NULL DEFAULT 'PAPER_SIGNAL')""")
    con.execute("""CREATE TABLE paper_outcomes (
      signal_id TEXT PRIMARY KEY, status TEXT NOT NULL, pnl_pts REAL NOT NULL,
      reviewed_utc TEXT NOT NULL)""")
    con.execute("""INSERT INTO signals
      (id,recorded_utc,candle_utc,epic,source,timeframe,strategy,action,reason)
      VALUES ('old','2026-11-04T12:00:00Z','2026-11-04T12:00:00Z',
       'US500','Capital.com DEMO REST','MINUTE','EMA TREND','LONG','legacy')""")
    con.execute("""INSERT INTO paper_outcomes(signal_id,status,pnl_pts,reviewed_utc)
         VALUES ('old','WIN',9.99,'2026-11-04T12:10:00Z')""")
    con.commit()
    con.close()
    con=connect(path)
    assert legacy_outcomes_count(con)==1
    assert len(recent(con))==1
    assert paper_report(con)==[]
    assert con.execute("SELECT model_version FROM paper_outcomes WHERE signal_id='old'").fetchone()[0]=='legacy_v1'


def test_signal_spread_is_frozen_at_signal_creation(tmp_path):
    con=connect(tmp_path/'paper.sqlite3')
    idx=pd.date_range('2026-11-04T12:00:00Z',periods=10,freq='min')
    mid=[100]*10
    candles=pd.DataFrame({'Open':mid,'High':[101]*10,'Low':[99]*10,'Close':mid},index=idx)
    candles.loc[idx[3],'High']=103
    d=Decision('LONG','EMA TREND','signal',100,98,102,2.0)
    assert archive(con,'A',idx[0].isoformat(),'US500','Capital.com DEMO REST','MINUTE',d,spread=.6)
    done=audit_prior_paper_signals(con,candles,'US500','Capital.com DEMO REST','MINUTE',
                                   spread=1.9,slippage=0)
    assert len(done)==1
    assert done[0]==('A','WIN',1.4)
    rep=paper_report(con)
    assert len(rep)==1
    assert rep[0]['entry_spread']==.6
    assert rep[0]['model_version']=='v2_mid_bidask'
    assert legacy_outcomes_count(con)==0
