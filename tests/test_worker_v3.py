"""Foreground worker v3 integration on synthetic DEMO: no network/real trades."""
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
from trader.market import Snapshot, PERIOD
from trader.strategy import Decision
from trader.storage import connect
from trader.paper_lifecycle import recent_positions
import trader.worker as worker

BASE=pd.Timestamp.now(tz="UTC").floor("min")-pd.Timedelta(minutes=2)

class FakeClient:
    environment="DEMO"
    def market_state(self,epic):return "TRADEABLE"

def snapshots(shift=0):
    result={}
    for tf,sec in PERIOD.items():
        # Stable 155 bars for each timeframe; 1-minute advances one bar.
        end=BASE+pd.Timedelta(minutes=shift)
        if tf!="MINUTE":
            end=end.floor(f"{sec}s")
        idx=pd.date_range(end=end,periods=155,freq=f"{sec}s",tz="UTC")
        p=np.full(155,100.0)
        frame=pd.DataFrame({"Open":p,"High":p+1,"Low":p-1,
             "Close":p,"Spread":np.full(155,.6)},index=idx)
        result[tf]=Snapshot(frame,"Capital.com DEMO REST","US500",tf,
             .6,end.to_pydatetime(),90,True,"OK synthetic",quote_spread=.6)
    return result

def setup(monkeypatch):
    def sample(*args,**kwargs):
        sample.calls+=1
        return snapshots(shift=min(sample.calls-1,1)),{}
    sample.calls=0
    monkeypatch.setattr(worker,"fetch_all_timeframes",sample)
    monkeypatch.setattr(worker,"current_feed_status",lambda snap,src:(True,"OK",0))
    monkeypatch.setattr(worker,"filter_mtf_decision",lambda dec,snaps,asof:(dec,[type("X",(),{"ready":True})()]*4))
    monkeypatch.setattr(worker,"decide_any",
        lambda frame,strategy,spread:Decision("LONG",strategy,"synthetic",100,98,102))
    monkeypatch.setattr(worker,"macro_blackout",lambda events:(False,"safe BLS"))
    return sample


def test_worker_v3_queues_then_opens_same_paper_database(monkeypatch,tmp_path):
    setup(monkeypatch)
    db=connect(tmp_path/"worker.sqlite3")
    cal=lambda:[{"data_utc":datetime.now(timezone.utc),"wydarzenie":"dummy"}]
    x=worker.scan_once(FakeClient(),"US500","MINUTE","EMA TREND",2,db,calendar_fetch=cal)
    assert "QUEUE=YES" in x
    assert recent_positions(db)[0]["status"]=="PENDING"
    y=worker.scan_once(FakeClient(),"US500","MINUTE","EMA TREND",2,db,calendar_fetch=cal)
    assert "ACTIVE=OPEN" in y
    rows=recent_positions(db)
    assert len(rows)==1
    assert rows[0]["entry_executable"]==100.55


def test_worker_fail_closed_on_macro_failure(monkeypatch,tmp_path):
    setup(monkeypatch)
    db=connect(tmp_path/"worker.sqlite3")
    def broken():
        raise ValueError("No calendar")
    v=worker.scan_once(FakeClient(),"US500","MINUTE","EMA TREND",2,db,calendar_fetch=broken)
    assert "MACRO_CALENDAR_UNAVAILABLE" in v
    assert recent_positions(db)==[]


def test_worker_rejects_live_client_even_when_market_says_tradeable(monkeypatch,tmp_path):
    setup(monkeypatch)
    db=connect(tmp_path/"worker.sqlite3")
    client=FakeClient()
    client.environment="LIVE"
    response=worker.scan_once(client,"US500","MINUTE","EMA TREND",2,db)
    assert "DEMO-only" in response
    assert recent_positions(db)==[]
