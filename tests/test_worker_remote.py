"""Cloud worker recovery and fail-closed checkpoint behaviors, without API access."""
import sqlite3
import pytest
from trader import worker
from trader.remote_checkpoint import RemoteError,RemoteConflict,dump_state
from trader.paper_lifecycle import recent_positions
from trader.strategy import Decision
from trader.paper_lifecycle import queue_paper
import pandas as pd

@pytest.fixture(autouse=True)
def no_external_rss_requests_in_tests(monkeypatch):
    # Worker regularly reads OFFICIAL headlines, but CI must not call the web.
    monkeypatch.setattr(worker,"fetch_headlines",lambda **kwargs:(
        [{"źródło":"FED","data_utc":"2026-11-05T20:00:00+00:00",
          "tytuł":"Economic review","url":"https://www.federalreserve.gov/"}],{}))


class Checkpoint:
    def __init__(self):
        self.v=0
        self.state={"schema":1,"tables":{}}
        self.writes=0
    def fetch(self):
        return self.v,self.state
    def save(self,version,payload):
        if version!=self.v:
            raise RemoteConflict("different writer")
        self.v+=1
        self.writes+=1
        self.state=payload
        return self.v


def test_cloud_restarts_restore_same_paper_state(monkeypatch):
    cp=Checkpoint()
    seen=[]
    def scan(client,epic,tf,strategy,max_spread,db,**kwargs):
        seen.append(len(recent_positions(db)))
        if not seen[-1]:
            queue_paper(db,epic,"Capital.com DEMO REST",tf,
                Decision("LONG",strategy,"synthetic",100,98,102),
                pd.Timestamp("2026-11-05T13:00Z"),.6)
        return "WAIT / synthetic simulation only"
    monkeypatch.setattr(worker,"scan_once",scan)
    first=worker.remote_scan_once(cp,object(),"US500","MINUTE","EMA TREND",2)
    second=worker.remote_scan_once(cp,object(),"US500","MINUTE","EMA TREND",2)
    assert seen==[0,1]  # separate sqlite memory DBs
    assert cp.v==2 and cp.writes==2
    assert cp.state["meta"]["epic"]=="US500"
    assert len(cp.state["tables"]["paper_positions_v3"])==1
    assert "TELEGRAM_REMOTE=DISABLED" in second
    assert "CLOUD_CHECKPOINT_VERSION=1" in first


def test_cloud_failure_does_not_claim_success_or_retry_network(monkeypatch):
    cp=Checkpoint()
    def scan(*args,**kwargs):
        raise RemoteError("API down")
    monkeypatch.setattr(worker,"scan_once",scan)
    with pytest.raises(RemoteError):
        worker.remote_scan_once(cp,object(),"US500","MINUTE","EMA TREND",2)
    assert cp.writes==0


def test_worker_remote_requires_github_cloud_secrets_not_local_fallback():
    from trader.remote_checkpoint import RemoteCheckpoint
    with pytest.raises(RemoteError):
        RemoteCheckpoint.from_env(env={})


def test_real_remote_scan_persists_cloud_ohlc_without_local_candle_history(monkeypatch):
    """Regression for real GH Actions failure: SQLite lacks candle_history."""
    from datetime import datetime, timezone
    from trader.market import Snapshot
    from trader.auto_strategy import AUTO_MODE
    from trader.strategy import Decision

    cp=Checkpoint()
    cp.ohlc_updates=0
    def cloud_upsert(snapshots,epic):
        assert "MINUTE" in snapshots and epic=="US500"
        cp.ohlc_updates+=1
        return 120
    cp.upsert_candles=cloud_upsert

    at=pd.Timestamp.now(tz="UTC").floor("min")-pd.Timedelta(minutes=2)
    idx=pd.date_range(end=at,periods=120,freq="min",tz="UTC")
    data=pd.DataFrame({"Open":[100.0]*120,"High":[101.0]*120,
       "Low":[99.0]*120,"Close":[100.0]*120,"Spread":[0.5]*120},index=idx)
    snap=Snapshot(data,"Capital.com DEMO REST","US500","MINUTE",
         0.5,at.to_pydatetime(),90,True,"OK synthetic",quote_spread=0.5)

    class Client:
        environment="DEMO"
        def market_state(self,epic): return "TRADEABLE"

    monkeypatch.setattr(worker,"fetch_all_timeframes",
        lambda *args,**kwargs:({"MINUTE":snap},{}))
    monkeypatch.setattr(worker,"current_feed_status",lambda *args:(True,"OK",0))
    def no_sql_archive(*args,**kwargs):
        raise AssertionError("remote must never attempt local candle_history")
    monkeypatch.setattr(worker,"archive_candles",no_sql_archive)
    waiting=Decision("WAIT",AUTO_MODE,"synthetic no signal")
    monkeypatch.setattr(worker,"evaluate_auto",
        lambda *args,**kwargs:(waiting,[]))
    ready=type("TF",(),{"ready":True,"trend":"NEUTRAL","timeframe":"MINUTE"})()
    monkeypatch.setattr(worker,"filter_mtf_decision",
        lambda *args,**kwargs:(waiting,[ready]*4))
    monkeypatch.setattr(worker,"decide_any",lambda *args,**kwargs:waiting)

    outcome=worker.remote_scan_once(cp,Client(),"US500","MINUTE",
        AUTO_MODE,2,strict_macro=False,enable_setups=False)
    assert cp.ohlc_updates==1
    assert cp.writes==1
    assert cp.v==1
    assert "CLOUD_CHECKPOINT_VERSION=1" in outcome
    assert "CANDLES=120" in outcome
    assert cp.state["meta"]["epic"]=="US500"
    assert cp.state["auto_ai"]=={}


def test_remote_ohlc_write_failure_prevents_billable_ai_and_checkpoint(monkeypatch):
    """Cloud OHLC failure must fail closed before the optional paid review."""
    from trader.market import Snapshot
    from trader.auto_strategy import AUTO_MODE
    cp=Checkpoint()
    cp.upsert_candles=lambda *args,**kwargs: (_ for _ in ()).throw(RemoteError("cloud unavailable"))
    at=pd.Timestamp.now(tz="UTC").floor("min")-pd.Timedelta(minutes=2)
    idx=pd.date_range(end=at,periods=120,freq="min",tz="UTC")
    data=pd.DataFrame({"Open":[100.0]*120,"High":[101.0]*120,
      "Low":[99.0]*120,"Close":[100.0]*120,"Spread":[0.5]*120},index=idx)
    snap=Snapshot(data,"Capital.com DEMO REST","US500","MINUTE",
         0.5,at.to_pydatetime(),90,True,"OK synthetic",quote_spread=0.5)
    class Client:
        environment="DEMO"
        def market_state(self,epic): return "TRADEABLE"
    monkeypatch.setattr(worker,"fetch_all_timeframes",
         lambda *a,**kw:({"MINUTE":snap},{}))
    monkeypatch.setattr(worker,"archive_candles",
         lambda *a,**kw:(_ for _ in ()).throw(AssertionError("wrong archive")))
    monkeypatch.setattr(worker,"review_closed_candle",
         lambda *a,**kw: (_ for _ in ()).throw(AssertionError("paid review invoked")),
         raising=False)
    with pytest.raises(RemoteError,match="cloud unavailable"):
        worker.remote_scan_once(cp,Client(),"US500","MINUTE",
             AUTO_MODE,2,strict_macro=False)
    assert cp.writes==0
