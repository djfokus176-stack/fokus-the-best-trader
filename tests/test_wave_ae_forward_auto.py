"""Automatic A–E research cannot backdate, double count or revise fills."""
import pandas as pd
import pytest

import trader.wave_ae_forward_auto as ae
from trader.wave_intelligence2 import VARIANTS


def _frame(count=222):
    dates=pd.date_range("2026-11-02T10:00:00Z",periods=count,freq="15min")
    return pd.DataFrame({"Open":100.,"High":101.,"Low":99.,"Close":100.,
                         "Spread":0.5},index=dates)


def _rows(frame, stamp, status="NO_NEXT_OPEN", pnl=None):
    out=[]
    for variant in VARIANTS:
        this_status = ("WAIT" if variant=="E_WAIT" else
                       status if variant=="A_RAW" else "NOT_TRIGGERED")
        out.append({
            "anchor_id":"anchor-1","anchor_utc":stamp,"anchor_side":"SHORT",
            "variant":variant,
            "direction":("LONG" if variant=="D_BREAKOUT_HOLD" else "SHORT"),
            "status":this_status,
            "signal_utc":stamp if variant=="A_RAW" else pd.NaT,
            "triggered":variant=="A_RAW","pnl_pts":(pnl if variant=="A_RAW" else None),
            "entry_utc":stamp+pd.Timedelta(minutes=15)
                if pnl is not None and variant=="A_RAW" else pd.NaT,
            "exit_utc":stamp+pd.Timedelta(minutes=30)
                if pnl is not None and variant=="A_RAW" else pd.NaT,
            "execution":"LAST_KNOWN_CLOSE_SPREAD_MODEL"
                if pnl is not None else None})
    return pd.DataFrame(out)


def test_priming_no_old_history_and_idempotent_new_m15(monkeypatch):
    frame=_frame()
    calls=[]
    confirmed=frame.index[217]
    def engine(f,**kwargs):
        calls.append((f.index[-1],kwargs))
        return pd.DataFrame(),_rows(f,confirmed),{}
    monkeypatch.setattr(ae,"run_wave_abcd",engine)
    prime=ae.advance_wave_ae_forward({},frame.iloc[:217])
    assert prime["status"]=="PRIMED_NO_HISTORICAL_BACKFILL"
    assert not prime["events"]
    assert not calls
    fresh=ae.advance_wave_ae_forward(prime,frame.iloc[:218])
    assert len(calls)==1
    assert len(fresh["events"])==1
    assert fresh["events"][0]["anchor_utc"]==confirmed.isoformat()
    assert set(fresh["events"][0]["variants"])==set(VARIANTS)
    assert fresh["events"][0]["variants"]["A_RAW"]["pnl_pts"] is None
    same=ae.advance_wave_ae_forward(fresh,frame.iloc[:218])
    assert same==fresh
    assert len(calls)==1
    assert ae.wave_ae_forward_scorecard(same)["trade_permission"]=="WAIT"
    assert ae.wave_ae_forward_scorecard(same)["closed_outcomes"]==0


def test_later_result_is_immutable_even_after_worse_replay(monkeypatch):
    frame=_frame()
    confirmed=frame.index[217]
    stage={"status":"NO_NEXT_OPEN","pnl":None}
    def engine(f,**kwargs):
        return None,_rows(f,confirmed,stage["status"],stage["pnl"]),{}
    monkeypatch.setattr(ae,"run_wave_abcd",engine)
    initial=ae.advance_wave_ae_forward({},frame.iloc[:217])
    first=ae.advance_wave_ae_forward(initial,frame.iloc[:218])
    stage.update(status="TP",pnl=7.5)
    settled=ae.advance_wave_ae_forward(first,frame.iloc[:219])
    row=settled["events"][0]["variants"]["A_RAW"]
    assert row["status"]=="TP"
    assert row["pnl_pts"]==7.5
    assert row["entry_utc"] is not None
    stage.update(status="SL",pnl=-18.25)
    after=ae.advance_wave_ae_forward(settled,frame.iloc[:220])
    assert after["events"][0]["variants"]["A_RAW"]==row
    score=ae.wave_ae_forward_scorecard(after)
    assert score["closed_outcomes"]==1
    short_a=next(r for r in score["rank"] if r["side"]=="SHORT"
                 and r["variant"]=="A_RAW")
    assert short_a["closed"]==1
    assert short_a["net_pts"]==7.5
    assert short_a["win_pct_descriptive"] is None
    assert short_a["profit_factor_descriptive"] is None
    short_wait=next(r for r in score["rank"] if r["side"]=="SHORT"
                    and r["variant"]=="E_WAIT")
    assert short_wait["closed"]==0
    assert short_wait["pending_or_untriggered"]==0
    assert score["independent_oos_verified"] is False
    assert score["calibrated_probability"] is False


def test_old_reappearing_anchors_never_counted_as_new_forward(monkeypatch):
    frame=_frame()
    old_stamp=frame.index[215]
    def engine(f,**kwargs):
        return None,_rows(f,old_stamp,"TP",3.25),{}
    monkeypatch.setattr(ae,"run_wave_abcd",engine)
    prime=ae.advance_wave_ae_forward({},frame.iloc[:217])
    later=ae.advance_wave_ae_forward(prime,frame.iloc[:218])
    assert later["events"]==[]
    assert ae.wave_ae_forward_scorecard(later)["events_forward"]==0


def test_cannot_roll_back_watermark_or_reinterpret_sources():
    frame=_frame()
    prime=ae.advance_wave_ae_forward({},frame.iloc[:217])
    with pytest.raises(ValueError,match="rewind"):
        ae.advance_wave_ae_forward(prime,frame.iloc[:215])
    with pytest.raises(ValueError,match="source"):
        ae.advance_wave_ae_forward(prime,frame.iloc[:218],source="LIVE")
    with pytest.raises(ValueError,match="schema"):
        ae.advance_wave_ae_forward({"schema":"other",
            "last_closed_utc":prime["last_closed_utc"]},frame.iloc[:218])


def test_bounded_archive_and_one_status_for_each_variant(monkeypatch):
    frame=_frame()
    stamp=frame.index[217]
    def engine(f,**kwargs):
        rows=_rows(f,stamp)
        return None,rows,{}
    monkeypatch.setattr(ae,"run_wave_abcd",engine)
    p=ae.advance_wave_ae_forward({},frame.iloc[:217])
    p=ae.advance_wave_ae_forward(p,frame.iloc[:218])
    assert len(ae.wave_ae_forward_scorecard(p)["rank"])==10
    assert all(r["status"] for r in ae.wave_ae_forward_scorecard(p)["rank"])
    assert ae.wave_ae_forward_scorecard(p)["trade_permission"]=="WAIT"
