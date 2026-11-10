"""No real Supabase credential is used. Test version CAS, restoration, RLS-safe API."""
import sqlite3
from urllib.parse import urlparse
import pytest
from trader.remote_checkpoint import (RemoteCheckpoint,RemoteError,RemoteConflict,
                                      dump_state,restore_state,remote_view_db)
from trader.paper_lifecycle import queue_paper,recent_positions,ensure_tables
from trader.strategy import Decision
import pandas as pd

KEY="sb_secret_"+("x"*48)
URL="https://isolated-fokus-trader.supabase.co"

class Response:
    def __init__(self,status,payload):
        self.status_code=status
        self.payload=payload
    def json(self):return self.payload

class FakeREST:
    def __init__(self):
        self.version=0
        self.payload={"schema":1,"tables":{}}
        self.candles={}
        self.calls=[]
    def request(self,method,url,headers=None,params=None,json=None,timeout=None):
        self.calls.append((method,url,headers))
        assert headers["apikey"]==KEY
        assert "Authorization" not in headers  # modern secret key, not JWT
        path=urlparse(url).path
        if path.endswith("/fokus_paper_checkpoint"):
            if method=="GET":
                return Response(200,[{"version":self.version,"payload":self.payload}])
            if method=="PATCH":
                if params["version"]!=f"eq.{self.version}":
                    return Response(200,[])
                self.version=json["version"]
                self.payload=json["payload"]
                return Response(200,[{"version":self.version}])
        if path.endswith("/fokus_closed_candles"):
            if method=="POST":
                for candle in json:
                    k=(candle["source"],candle["epic"],candle["timeframe"],candle["candle_utc"])
                    self.candles[k]=candle
                return Response(201,None)
            if method=="GET":
                all_data=[{
                    "candle_utc":r["candle_utc"],"open":r["open"],"high":r["high"],
                    "low":r["low"],"close":r["close"],"spread":r["spread"]}
                    for r in self.candles.values()]
                all_data.sort(key=lambda x:x["candle_utc"],reverse=True)
                start=int(params["offset"]);length=int(params["limit"])
                return Response(200,all_data[start:start+length])
        return Response(404,{"error":"bad"})

def make():
    mock=FakeREST()
    return RemoteCheckpoint(URL,KEY,session=mock),mock

def test_remote_version_compare_and_swap_rejects_stale_writer():
    remote,mock=make()
    version,data=remote.fetch()
    assert version==0
    assert remote.save(version,data)==1
    with pytest.raises(RemoteConflict):
        remote.save(version,data)
    assert remote.fetch()[0]==1

def test_restore_v3_roundtrip_then_remote_view(tmp_path):
    db=sqlite3.connect(":memory:")
    ensure_tables(db)
    t=pd.Timestamp("2026-11-05T10:00Z")
    x=queue_paper(db,"US500","Capital.com DEMO REST","MINUTE",
                  Decision("LONG","EMA TREND","test",100,98,102),t,.6)
    assert x
    payload=dump_state(db)
    remote,mock=make()
    remote.save(0,payload)
    view,version=remote_view_db(remote)
    assert version==1
    assert recent_positions(view)[0]["trade_id"]==x
    with pytest.raises(RemoteError):
        restore_state(view,payload,only_empty=True)

def test_bad_secret_or_url_fail_closed():
    for url in ("http://foo.supabase.co","https://evil.example","https://a.supabase.co.evil.org"):
        with pytest.raises(RemoteError):RemoteCheckpoint(url,KEY)
    with pytest.raises(RemoteError):RemoteCheckpoint(URL,"short")

def test_cloud_upsert_ohlc_deduplicates():
    from types import SimpleNamespace
    remote,mock=make()
    ix=pd.date_range("2026-11-04T13:01Z",periods=3,freq="min")
    frame=pd.DataFrame({"Open":[100.]*3,"High":[101.]*3,"Low":[99.]*3,
                        "Close":[100.]*3,"Spread":[.6]*3},index=ix)
    sn=SimpleNamespace(good=True,source="Capital.com DEMO REST",
                       epic="US500",frame=frame)
    assert remote.upsert_candles({"MINUTE":sn},"US500")==3
    assert remote.upsert_candles({"MINUTE":sn},"US500")==3
    assert len(mock.candles)==3
    assert all(x["spread"]==.6 for x in mock.candles.values())

def test_cloud_rejects_wrong_schema_and_doesnt_overwrite(tmp_path):
    remote,mock=make()
    mock.payload={"schema":15,"tables":{}}
    with pytest.raises(RemoteError):remote.fetch()
    with pytest.raises(RemoteError):remote.save(0,{"schema":999})
    assert mock.version==0

def test_cloud_http_error_redacts_body_and_key():
    remote,mock=make()
    class ErrorREST(FakeREST):
        def request(self,*args,**kw):
            return Response(401,{"sensitive":KEY})
    remote.http=ErrorREST()
    with pytest.raises(RemoteError) as exc:
        remote.fetch()
    assert KEY not in str(exc.value)
    assert "HTTP 401" in str(exc.value)


def test_remote_candle_pagination_and_order():
    remote,mock=make()
    from types import SimpleNamespace
    import pandas as pd
    ix=pd.date_range("2026-11-04T13:01Z",periods=1105,freq="min")
    arr=[100.0+i*.01 for i in range(len(ix))]
    frame=pd.DataFrame({"Open":arr,"High":[x+1 for x in arr],
        "Low":[x-1 for x in arr],"Close":arr,"Spread":[.6]*len(ix)},index=ix)
    sn=SimpleNamespace(good=True,source="Capital.com DEMO REST",epic="US500",frame=frame)
    remote.upsert_candles({"MINUTE":sn},"US500",max_per_tf=1105)
    read=remote.fetch_candles("US500","MINUTE",limit=1105)
    assert len(read)==1105
    assert read.index.is_monotonic_increasing
    assert read.index[0]==ix[0] and read.index[-1]==ix[-1]
    assert read.Close.iloc[-1]==arr[-1]


def test_worker_logs_sanitized_supabase_error_but_not_untrusted_errors(monkeypatch,capsys):
    """Hosted PAPER troubleshooting must show status without leaking secrets."""
    from trader import worker
    from types import SimpleNamespace
    monkeypatch.setattr(worker,"configured",lambda: True)
    monkeypatch.setattr(worker,"RemoteCheckpoint",
        SimpleNamespace(from_env=lambda: object()))
    monkeypatch.setattr(worker,"CapitalReadOnly",lambda *args,**kw: object())
    monkeypatch.setenv("FOKUS_CANDLE_TIME_CONFIRMED","open")

    def fail_with(exc):
        def fail(*args,**kwargs):
            raise exc
        monkeypatch.setattr(worker,"remote_scan_once",fail)
        with pytest.raises(SystemExit) as stopped:
            worker.main(["--once"])
        assert stopped.value.code==1
        return capsys.readouterr().out

    output=fail_with(RemoteError("Supabase HTTP 401 (check secret key)"))
    assert "WORKER ERROR: RemoteError / Supabase HTTP 401" in output
    output=fail_with(ValueError("possible-credential-leak"))
    assert "WORKER ERROR: ValueError" in output
    assert "possible-credential-leak" not in output
