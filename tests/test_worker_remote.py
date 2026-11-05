"""Cloud worker recovery and fail-closed checkpoint behaviors, without API access."""
import sqlite3
import pytest
from trader import worker
from trader.remote_checkpoint import RemoteError,RemoteConflict,dump_state
from trader.paper_lifecycle import recent_positions
from trader.strategy import Decision
from trader.paper_lifecycle import queue_paper
import pandas as pd


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
