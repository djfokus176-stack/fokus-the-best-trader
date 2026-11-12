"""Tests: WAVE archive needs closed M15, idempotence, causal outcomes and CAS."""
import pandas as pd
import numpy as np
import pytest

from trader.wave_shadow_archive import (
    advance_wave_shadow,wave_shadow_scorecard,MAX_EVENTS)


def sample_m15():
    times=[]
    for d in pd.bdate_range("2026-10-23",periods=14):
        first=pd.Timestamp(str(d.date())+" 09:45",tz="America/New_York")
        times.extend(pd.date_range(first,periods=26,freq="15min"))
    idx=pd.DatetimeIndex(times).tz_convert("UTC")
    frame=pd.DataFrame({"Open":100.,"High":102.,"Low":99.,
                        "Close":100.,"Spread":.6},index=idx)
    start=len(frame)-26
    for i,p in ((3,110.),(11,110.2),(19,110.1)):
        frame.iloc[start+i,frame.columns.get_loc("High")]=p
    for i,p in ((7,95.),(15,96.)):
        frame.iloc[start+i,frame.columns.get_loc("Low")]=p
    frame.iloc[start+22,frame.columns.get_loc("Close")]=95.5
    frame.iloc[start+22,frame.columns.get_loc("Low")]=94.5
    return frame


def test_backfill_is_not_forward_and_repeated_scan_is_identical():
    frame=sample_m15()
    first=advance_wave_shadow({},frame.iloc[:-5])
    assert first["events_forward"]==0
    assert all(e["origin"]=="BACKFILL" for e in first["events"])
    assert advance_wave_shadow(first,frame.iloc[:-5])==first
    later=advance_wave_shadow(first,frame.iloc[:-4])
    fresh=[e for e in later["events"] if e["origin"]=="FORWARD"]
    assert fresh and any(e["wave_count"]==3 for e in fresh)
    assert all(pd.Timestamp(e["signal_utc"]) <= frame.index[-5]
               for e in fresh)
    assert len(set(e["event_id"] for e in later["events"]))==len(later["events"])
    assert advance_wave_shadow(later,frame.iloc[:-4])==later


def test_1hour_horizon_closes_only_after_four_subsequent_m15():
    frame=sample_m15()
    first=advance_wave_shadow({},frame.iloc[:-5])
    peak=advance_wave_shadow(first,frame.iloc[:-4])
    found=next(e for e in peak["events"]
               if e["origin"]=="FORWARD" and e["wave_count"]==3
               and e["side"]=="SHORT")
    assert "60m_0.5pct" not in found["outcomes"]
    result=advance_wave_shadow(peak,frame)
    ev=next(e for e in result["events"] if e["event_id"]==found["event_id"])
    label=ev["outcomes"]["60m_0.5pct"]
    assert label["status"]=="CLOSED"
    assert isinstance(label["up"],bool) and isinstance(label["down"],bool)
    assert label["both"] == (label["up"] and label["down"])
    assert label["flat"] == (not label["up"] and not label["down"])
    assert pd.Timestamp(label["resolved_utc"])<=frame.index[-1]
    assert "120m_0.5pct" not in ev["outcomes"]
    assert wave_shadow_scorecard(result)["trade_permission"]=="WAIT"
    assert wave_shadow_scorecard(result)["forward_events"]>=1


def test_gap_and_expired_timestamp_never_score_as_success():
    frame=sample_m15()
    initial=advance_wave_shadow({},frame.iloc[:-5])
    peak=advance_wave_shadow(initial,frame.iloc[:-4])
    # Delete the first future candle, but extend last after the expected
    # horizon; absence must not be interpreted as win or loss.
    broken=frame.drop(frame.index[-4])
    later=advance_wave_shadow(peak,broken)
    ev=next(e for e in later["events"] if e["origin"]=="FORWARD"
            and e["wave_count"]==3)
    assert ev["outcomes"]["60m_0.5pct"]["status"]=="INVALIDATED_GAP"
    with pytest.raises(ValueError,match="older"):
        advance_wave_shadow(later,frame.iloc[:-6])


def test_feed_scope_cap_and_missing_closed_clock_fail_closed():
    f=sample_m15()
    with pytest.raises(ValueError,match="only"):
        advance_wave_shadow({},f,source="Capital.com LIVE REST")
    with pytest.raises(ValueError,match="bounded"):
        advance_wave_shadow({},f,cap=MAX_EVENTS+1)
    bad=f.copy()
    bad.index=bad.index.tz_localize(None)
    with pytest.raises(ValueError,match="timezone"):
        advance_wave_shadow({},bad)
    bad=f.copy()
    bad.index=bad.index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="15-minute"):
        advance_wave_shadow({},bad)
    first=advance_wave_shadow({},f)
    with pytest.raises(ValueError,match="mismatch"):
        advance_wave_shadow(first,f,epic="NAS100")


def test_remote_cas_checkpoint_persists_shadow_state_without_paper_schema_change(monkeypatch):
    from trader import worker
    from trader.remote_checkpoint import dump_state,restore_state
    import sqlite3

    frame=sample_m15()
    class Cloud:
        def __init__(self):
            self.version=0
            self.state={"schema":1,"tables":{}}
        def fetch(self):
            return self.version,self.state
        def save(self,expected,payload):
            assert expected==self.version
            self.state=payload
            self.version+=1
            return self.version
    cp=Cloud()
    class Snapshot:
        source="Capital.com DEMO REST"
        def __init__(self,frame):self.frame=frame

    def fake_scan(client,epic,tf,strategy,maximum,db,**kwargs):
        assert kwargs["learning"] is not None
        cb=kwargs.get("wave_audit")
        assert cb is not None
        cb(Snapshot(frame.iloc[:-4] if cp.version==0 else frame))
        return "WAIT / dummy, WAVE audit only"
    monkeypatch.setattr(worker,"scan_once",fake_scan)
    monkeypatch.setattr(worker,"fetch_headlines",lambda **kwargs:([],{}))
    monkeypatch.setattr(worker,"shadow_scorecard",lambda state:{
        "leader":None,"reliable":False})
    monkeypatch.setenv("FOKUS_WAVE_SHADOW_ENABLED","true")
    worker.remote_scan_once(cp,object(),"US500","MINUTE",
        "EMA TREND",2,clock_confirmed_open=True)
    assert cp.state["wave_shadow"]["schema"]=="wave_shadow_v1"
    assert cp.state["meta"]["wave_shadow_status"].startswith("OK_M15")
    worker.remote_scan_once(cp,object(),"US500","MINUTE",
        "EMA TREND",2,clock_confirmed_open=True)
    assert cp.version==2
    assert cp.state["wave_shadow"]["last_closed_utc"]==frame.index[-1].isoformat()
    assert cp.state["wave_shadow_report"]["trade_permission"]=="WAIT"
    assert cp.state["schema"]==1
    assert cp.state["tables"].keys()>= {"paper_positions_v3"}
