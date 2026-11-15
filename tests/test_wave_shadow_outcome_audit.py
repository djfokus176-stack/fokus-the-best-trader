"""Regression tests for transparent WAVE SHADOW condition accounting."""
from trader.wave_shadow_archive import wave_shadow_scorecard


def test_audit_counts_each_status_without_treating_invalid_as_loss():
    state={"last_closed_utc":"2026-11-13T21:45:00+00:00","events":[
        {"origin":"BACKFILL","side":"LONG","wave_count":3,
         "confirmation":"BOS","outcomes":{
             "60m_0.25pct":{"status":"CLOSED","up":True,"down":False,
                            "both":False,"flat":False},
             "60m_0.5pct":{"status":"INVALIDATED_GAP"},
         }},
        {"origin":"FORWARD","side":"SHORT","wave_count":4,
         "confirmation":"REJECTION","outcomes":{
             "120m_0.25pct":{"status":"CLOSED","up":False,"down":True,
                             "both":False,"flat":False},
             "120m_0.5pct":{"status":"INVALIDATED_SESSION"},
             "240m_0.25pct":{"status":"INVALIDATED_MISSING_BARS"},
         }},
    ]}
    report=wave_shadow_scorecard(state)
    assert report["retained_events"]==2
    assert report["forward_events"]==1
    assert report["resolved_conditions"]==2
    assert report["invalidated_conditions"]==3
    assert report["pending_conditions"]==13
    assert report["invalidated_by_reason"]=={
        "INVALIDATED_GAP":1,
        "INVALIDATED_SESSION":1,
        "INVALIDATED_MISSING_BARS":1,
    }
    assert report["by_origin_side"]["BACKFILL|LONG"]=={
        "events":1,"resolved_conditions":1,
        "invalidated_conditions":1,"pending_conditions":7}
    assert report["by_origin_side"]["FORWARD|SHORT"]=={
        "events":1,"resolved_conditions":1,
        "invalidated_conditions":2,"pending_conditions":6}
    assert report["trade_permission"]=="WAIT"
    assert sum(v["n"] for v in report["groups"].values())==2


def test_empty_and_pending_events_preserve_backward_compatible_report():
    empty=wave_shadow_scorecard({})
    assert empty["resolved_conditions"]==0
    assert empty["invalidated_conditions"]==0
    assert empty["pending_conditions"]==0
    assert empty["trade_permission"]=="WAIT"
    state={"events":[{"origin":"FORWARD","side":"LONG","wave_count":3,
                      "confirmation":"BOS","outcomes":{}}]}
    r=wave_shadow_scorecard(state)
    assert r["pending_conditions"]==9
    assert r["resolved_conditions"]==0
    assert r["invalidated_conditions"]==0
    assert r["forward_events"]==1
    assert r["trade_permission"]=="WAIT"


def test_market_closure_retains_wave_archive_without_false_not_configured(monkeypatch):
    from datetime import datetime, timezone
    from trader import worker

    now=datetime.now(timezone.utc).isoformat()
    old_wave={"schema":"wave_shadow_v1","last_closed_utc":"2026-11-13T21:45:00+00:00",
              "events":[],"events_forward":0}
    class Cloud:
        def __init__(self):
            self.version=3
            self.payload={"schema":1,"tables":{},"wave_shadow":old_wave,
                          "news_radar":{"last_fetch_utc":now},
                          "macro_watch":{"asof_utc":now}}
        def fetch(self):
            return self.version,self.payload
        def save(self,expected,payload):
            assert expected==self.version
            self.version+=1
            self.payload=payload
            return self.version
    cloud=Cloud()
    monkeypatch.delenv("FOKUS_WAVE_SHADOW_ENABLED",raising=False)
    monkeypatch.setattr(worker,"scan_once",lambda *args,**kw:"WAIT / MARKET_CLOSED")
    worker.remote_scan_once(cloud,object(),"US500","MINUTE",
                            "EMA TREND",2.0,clock_confirmed_open=True)
    assert cloud.payload["meta"]["wave_shadow_status"]=="NO_NEW_M15"
    assert cloud.payload["wave_shadow"]["last_closed_utc"]==old_wave["last_closed_utc"]
    assert cloud.payload["wave_shadow_report"]["trade_permission"]=="WAIT"
