"""Regression tests: forward condition counts must not become A–E wins."""
import pandas as pd
import pytest

from trader.wave_forward_monitor import audit_wave_forward, STATUS


def _closed(up=False,down=False):
    return {"status":"CLOSED","up":bool(up),"down":bool(down),
            "both":bool(up and down),"flat":bool(not up and not down)}


def _event(identifier,side,origin,utc,outcomes=None):
    return {"event_id":identifier,"side":side,"origin":origin,
            "signal_utc":utc,"outcomes":outcomes or {}}


def _get(result,side,minutes,threshold):
    data=result["cohorts"]
    rows=data[(data.side==side) & (data.minutes==minutes) &
              (data.threshold_pct==threshold)]
    assert len(rows)==1
    return rows.iloc[0]


def test_forward_vs_historical_uses_disjoint_sources_and_only_forward():
    state={"schema":"wave_shadow_v1","epic":"US500",
           "source":"Capital.com DEMO REST",
           "last_closed_utc":"2026-11-13T21:45:00+00:00","events":[
       _event("old","LONG","BACKFILL","2026-11-10T10:00:00+00:00",{
           "60m_0.25pct":_closed(up=True)}),
       _event("f1","LONG","FORWARD","2026-11-12T14:30:00+00:00",{
           "60m_0.25pct":_closed(up=True),
           "60m_0.5pct":{"status":"INVALIDATED_GAP"},
           "120m_0.25pct":_closed(up=True,down=True)}),
       _event("f2","SHORT","FORWARD","2026-11-12T15:15:00+00:00",{
           "60m_0.25pct":_closed(),
           "60m_0.5pct":_closed(down=True),
           "240m_1pct":{"status":"CLOSED","up":True,"down":False,
                         "both":True,"flat":False}}),
    ]}
    audit=audit_wave_forward(state)
    assert audit["retained_events"]==3
    assert audit["forward_events"]==2
    assert audit["forward_sessions"]==1
    assert audit["trade_permission"]=="WAIT"
    assert audit["calibrated_probability"] is False
    assert audit["comparable_to_historical_ae"] is False
    assert audit["reason"]==STATUS
    l=_get(audit,"LONG",60,.25)
    assert (l["events"],l["sessions"],l["resolved"],
            l["up_only"],l["down_only"],l["both"],l["flat"])==(1,1,1,1,0,0,0)
    both=_get(audit,"LONG",120,.25)
    assert (both["resolved"],both["both"],both["up_only"],both["down_only"])==(1,1,0,0)
    invalid=_get(audit,"LONG",60,.5)
    assert (invalid["invalidated"],invalid["pending"],invalid["resolved"])==(1,0,0)
    flat=_get(audit,"SHORT",60,.25)
    assert (flat["resolved"],flat["flat"])==(1,1)
    down=_get(audit,"SHORT",60,.5)
    assert (down["resolved"],down["down_only"])==(1,1)
    bad=_get(audit,"SHORT",240,1.)
    assert (bad["bad"],bad["resolved"],bad["invalidated"])==(1,0,0)
    assert int(audit["cohorts"]["resolved"].sum())==4
    assert int(audit["cohorts"]["invalidated"].sum())==1
    assert int(audit["cohorts"]["bad"].sum())==1
    assert int(audit["cohorts"]["pending"].sum())==12
    assert len(audit["cohorts"])==18

    benchmark=audit["reference"]
    assert len(benchmark)==10
    short_raw=benchmark[(benchmark.LONG_SHORT=="SHORT")&
                        (benchmark.FORMACJA=="A_RAW")].iloc[0]
    assert int(short_raw.PROBY_OOS)==65
    assert float(short_raw.NETTO_OOS)==-427.73
    assert "events" not in benchmark.columns


def test_backfill_is_not_forward_even_if_outcome_closed():
    result=audit_wave_forward({"events":[_event(
        "old","SHORT","BACKFILL","2026-11-13T12:00:00Z",{
        "60m_0.25pct":_closed(down=True)})]})
    assert result["forward_events"]==0
    assert int(result["cohorts"]["resolved"].sum())==0
    assert result["trade_permission"]=="WAIT"


@pytest.mark.parametrize("bad",[
    [_event("dup","LONG","FORWARD","2026-11-13T12:00:00Z"),
     _event("dup","LONG","FORWARD","2026-11-13T12:15:00Z")],
    [_event("nozone","LONG","FORWARD","2026-11-13 12:00:00")],
    [_event("wrongside","BUY","FORWARD","2026-11-13T12:00:00Z")],
    [_event("","LONG","FORWARD","2026-11-13T12:00:00Z")],
])
def test_corrupt_forward_events_fail_closed(bad):
    with pytest.raises(ValueError):
        audit_wave_forward({"events":bad})


def test_reference_is_verified_structure_not_user_substituted_comparison():
    state={"events":[]}
    with pytest.raises(ValueError,match="rankingu"):
        audit_wave_forward(state,reference=pd.DataFrame({"side":["LONG"]}))


def test_pending_and_invalidated_are_not_relabelled_losses():
    state={"events":[_event("a","SHORT","FORWARD","2026-11-13T10:00:00Z",{
        "60m_0.25pct":{"status":"INVALIDATED_SESSION"},
        "120m_0.25pct":{"status":"INVALIDATED_GAP"}})]}
    a=audit_wave_forward(state)
    assert int(a["cohorts"]["resolved"].sum())==0
    assert int(a["cohorts"]["invalidated"].sum())==2
    assert int(a["cohorts"]["pending"].sum())==7
    assert all(a["cohorts"][x].sum()==0
               for x in ("up_only","down_only","both","flat"))
