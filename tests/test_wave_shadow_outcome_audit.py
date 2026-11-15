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
