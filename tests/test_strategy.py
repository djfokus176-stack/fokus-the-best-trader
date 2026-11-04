from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
from trader.market import parse_prices, evaluate_snapshot
from trader.strategy import Decision, decide, simulate_outcome, indicators
from trader.storage import connect, archive, recent, recent_scan_decisions

def data(n=120,trending=1):
    idx=pd.date_range('2026-11-04 12:00',periods=n,freq='min',tz='UTC')
    p=5000+np.arange(n)*trending*.4+np.sin(np.arange(n))*.6
    return pd.DataFrame({'Open':p-.1,'Close':p,'High':p+.5,'Low':p-.6,
                         'Spread':np.full(n,.6)},index=idx)

def test_snapshot_requires_successor_candle():
    d=data()
    now=d.index[-1].to_pydatetime()+timedelta(seconds=20)
    snap=evaluate_snapshot(d,'US500','MINUTE',now=now)
    assert snap.good and len(snap.frame)==119
    assert snap.confirmed_utc==d.index[-2].to_pydatetime()

def test_stale_is_wait():
    d=data()
    snap=evaluate_snapshot(d,'US500','MINUTE',now=datetime(2026,11,6,tzinfo=timezone.utc))
    assert not snap.good and 'przestarzałe' in snap.reason

def test_no_future_leakage_indicator():
    d=data()
    a=indicators(d.iloc[:-1]).iloc[-1]
    d.loc[d.index[-1],'Close']=1000000
    b=indicators(d.iloc[:-1]).iloc[-1]
    assert a.EMA9==b.EMA9

def test_wait_on_no_setup():
    assert decide(data(120,0),'DRUGA FALA').action=='WAIT'

def test_stop_wins_intrabar_long_short():
    idx=pd.date_range('2026-11-04',periods=3,freq='min',tz='UTC')
    bars=pd.DataFrame({'Open':[100,100,100],'High':[100,105,100],
                       'Low':[100,95,100],'Close':[100,100,100]},index=idx)
    assert simulate_outcome(bars,'LONG',100,97,103,.2)[0]=='LOSS'
    assert simulate_outcome(bars,'SHORT',100,103,97,.2)[0]=='LOSS'

def test_both_geometry_and_no_synthetic_trade():
    for action,stop,target in [('LONG',99,102),('SHORT',101,98)]:
        dec=Decision(action,'TEST','',100,stop,target)
        assert (stop<dec.entry<target) if action=='LONG' else (target<dec.entry<stop)

def test_idempotent_archive(tmp_path):
    con=connect(tmp_path/'x.sqlite3')
    d=Decision('WAIT','DRUGA FALA','test')
    args=(con,'event1','2026-11-04T12:00:00+00:00','US500','Capital DEMO','MINUTE',d)
    assert archive(*args)
    assert not archive(*args)
    assert len(recent(con))==0
    assert len(recent_scan_decisions(con))==1

def test_forward_audit_when_new_candles_arrive(tmp_path):
    from trader.storage import audit_prior_paper_signals,paper_report
    con=connect(tmp_path/'paper.sqlite3')
    d=data(120,0)
    dec=Decision('LONG','EMA TREND','test setup',float(d.Close.iloc[90]),
                 float(d.Close.iloc[90]-2),float(d.Close.iloc[90]+2),2.0)
    assert archive(con,'new',d.index[90].isoformat(),'US500','Capital.com DEMO REST','MINUTE',dec,spread=.6)
    first=audit_prior_paper_signals(con,d.iloc[:91],'US500','Capital.com DEMO REST','MINUTE',.6)
    assert first==[]
    later=audit_prior_paper_signals(con,d,'US500','Capital.com DEMO REST','MINUTE',.6)
    assert len(later)==1 and later[0][1] in {'WIN','LOSS','TIMEOUT','SKIPPED_GAP'}
    assert not audit_prior_paper_signals(con,d,'US500','Capital.com DEMO REST','MINUTE',.6)
    assert len(paper_report(con))==1

def test_capital_parser_keeps_spread_and_utc():
    p={'prices':[{'snapshotTimeUTC':'2026-11-04T13:05:00',
        'openPrice':{'bid':100,'ask':100.6},
        'highPrice':{'bid':101,'ask':101.6},
        'lowPrice':{'bid':99,'ask':99.6},
        'closePrice':{'bid':100.2,'ask':100.8}}]}
    df=parse_prices(p)
    assert df.index.tz is not None and abs(df.Spread.iloc[0]-.6)<1e-8
    assert abs(df.Close.iloc[0]-100.5)<1e-8
