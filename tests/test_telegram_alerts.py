"""Mock Telegram send: deduplicated on restarts; never send before opt-in."""
import pandas as pd
from trader.storage import connect
from trader.strategy import Decision
from trader.paper_lifecycle import ensure_tables,queue_paper,progress_paper
from trader.telegram_alerts import dispatch_alerts,record_stale_event

TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"
CHAT="123456789"
SRC="Capital.com DEMO REST"

def setup(tmp_path):
    db=connect(tmp_path/"alerts.sqlite3")
    ensure_tables(db)
    signal=pd.Timestamp.now(tz="UTC").floor("min")
    dec=Decision("LONG","EMA TREND","PAPER test",100,98,102)
    queue_paper(db,"US500",SRC,"MINUTE",dec,signal,.6,slippage=0)
    return db,signal

def test_no_telegram_without_opt_in_or_credentials(tmp_path):
    db,_=setup(tmp_path)
    sent=[]
    post=lambda *a,**kw: sent.append(1)
    assert dispatch_alerts(db,TOKEN,CHAT,enabled=False,post=post)["attempted"]==0
    assert dispatch_alerts(db,"badtoken",CHAT,enabled=True,post=post)["attempted"]==0
    assert sent==[]

def test_dedup_across_db_restart(tmp_path):
    db,t=setup(tmp_path)
    calls=[]
    class Response:
        status_code=200
        def json(self):return {"ok":True}
    def fake_post(url,**kwargs):
        assert "/sendMessage" in url
        assert "PAPER" in kwargs["data"]["text"]
        calls.append(url)
        return Response()
    r=dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fake_post)
    assert r["attempted"]==1 and r["sent"]==1
    assert dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fake_post)["attempted"]==0
    db.close()
    db=connect(tmp_path/"alerts.sqlite3")
    assert dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fake_post)["attempted"]==0
    assert len(calls)==1

def test_failed_alert_does_not_retry_and_stale_throttles(tmp_path):
    db,t=setup(tmp_path)
    class Broken:
        status_code=500
        def json(self):return {"ok":False}
    sent=[]
    def fail(url,**kw):
        sent.append(kw)
        return Broken()
    result=dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fail)
    assert result["failed"]==1
    assert dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fail)["attempted"]==0
    stamp=pd.Timestamp.now(tz="UTC")
    first=record_stale_event(db,SRC,"US500","MINUTE","API stale",stamp)
    second=record_stale_event(db,SRC,"US500","MINUTE","API stale",stamp)
    assert first==second
    assert record_stale_event(db,"Capital.com LIVE REST","US500","MINUTE","stale") is None
    res=dispatch_alerts(db,TOKEN,CHAT,enabled=True,post=fail)
    assert res["attempted"]==1
