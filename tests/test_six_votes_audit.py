"""Read-only six-vote forensic diagnostics, with all existing PAPER gates intact."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pandas as pd
from trader import worker
from trader.auto_strategy import AUTO_MODE
from trader.bls_verified_snapshot import verified_schedule


def test_vote_audit_persists_all_six_without_unlocking_wait(monkeypatch):
    now=datetime.now(timezone.utc)
    iso=now.isoformat()
    state={"schema":1,"tables":{},"news_radar":{"last_fetch_utc":iso},
           "macro_watch":{"asof_utc":iso,"sources":{}}}
    class FakeRemote:
        def __init__(self):
            self.state=state
            self.version=22
            self.saves=[]
        def fetch(self):
            return self.version,self.state
        def save(self,version,payload):
            assert version==self.version
            self.saves.append(payload)
            self.state=payload
            self.version+=1
            return self.version
    remote=FakeRemote()
    calls=[]
    names=("DRUGA FALA","EMA TREND","LIQUIDITY SWEEP",
           "BREAKOUT RETEST","EMA PULLBACK","VOLATILITY BREAKOUT")
    raw=["LONG","WAIT","SHORT","WAIT","WAIT","WAIT"]
    after=["WAIT","WAIT","WAIT","WAIT","WAIT","WAIT"]
    votes=[{"Strategia":name,"Setup OHLC":r,"Po filtrze MTF":m,
            "Powód":"MTF: brak zgodności M5/M15/H1" if r!="WAIT" else "Brak układu"}
           for name,r,m in zip(names,raw,after)]
    tf=[SimpleNamespace(timeframe=n,ready=True,trend="DOWN",
          reason="OK",candle_utc=now) for n in ("MINUTE","MINUTE_5","MINUTE_15","HOUR")]
    snapshot=SimpleNamespace(good=False,confirmed_utc=now,epic="US500",
                             source="Capital.com DEMO REST",resolution="MINUTE")
    decision=SimpleNamespace(action="WAIT",strategy=AUTO_MODE,reason="0/2")
    def fake_scan(client,epic,tfname,strategy,max_spread,db,*,reviewer,**kwargs):
        calls.append((epic,strategy,kwargs.get("strict_macro")))
        reviewer(snapshot,decision,votes,tf,[])
        return now.isoformat()+" / WAIT / QUEUE=NO / ACTIVE=NONE / GATES=OK"
    monkeypatch.setattr(worker,"scan_once",fake_scan)
    monkeypatch.setattr(worker,"decide_any",lambda *a,**kw:decision)
    monkeypatch.setenv("FOKUS_AUTO_AI_ENABLED","false")
    result=worker.remote_scan_once(remote,object(),"US500","MINUTE",AUTO_MODE,2.0)
    assert "SIX_VOTES=" in result
    assert "MTF_VETO=" in result
    assert "QUEUE=NO" in result
    assert calls==[("US500",AUTO_MODE,True)]
    audit=remote.state["last_vote_audit"]
    assert len(audit["rows"])==6
    assert [x["raw"] for x in audit["rows"]]==raw
    assert [x["after_mtf"] for x in audit["rows"]]==after
    assert len(audit["mtf"])==4
    assert remote.state["tables"]["paper_positions_v3"]==[]


def test_expired_bls_snapshot_never_extends_implicitly():
    from trader.bls_verified_snapshot import VALID_UNTIL_UTC
    import pytest
    assert VALID_UNTIL_UTC==datetime(2026,11,10,0,0,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="BLS_VERIFIED_SNAPSHOT_EXPIRED"):
        verified_schedule(now=VALID_UNTIL_UTC)
    assert verified_schedule(now=VALID_UNTIL_UTC-timedelta(hours=12))


def test_stale_six_vote_audit_must_not_be_presented_as_live():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text("utf-8")
    assert "last_vote_audit" in (Path(__file__).resolve().parents[1]/
                                 "trader/worker.py").read_text("utf-8")
    assert "To ostatnia ZAPISANA diagnoza, nie stan live" in app
