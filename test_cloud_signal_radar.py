"""Offline proof that CLOUD radar displays worker observations, never tips."""
from copy import deepcopy
from pathlib import Path

from trader.cloud_signal_radar import worker_signal_radar


CANDLE="2026-11-17T14:10:00+00:00"
SCAN="2026-11-17T14:11:16+00:00"
NOW="2026-11-17T14:11:22+00:00"
METHODS=("DRUGA FALA","EMA TREND","LIQUIDITY SWEEP",
         "BREAKOUT RETEST","EMA PULLBACK","VOLATILITY BREAKOUT")


def fixture():
    rows=[
        {"strategy":method,"raw":"WAIT","after_mtf":"WAIT",
         "reason":"Brak pełnego układu"} for method in METHODS
    ]
    stages=[
        {"strategy":method,"stage":0,"side":"BRAK",
         "criteria":[{"name":"Trend", "ok":False},
                     {"name":"Potwierdzenie", "ok":False},
                     {"name":"Setup + MTF + bramki", "ok":False}]}
        for method in METHODS
    ]
    return {
        "meta":{
            "source":"Capital.com DEMO REST", "epic":"US500",
            "strategy":"AUTO — 6 STRATEGII",
            "last_scan_utc":SCAN,
            "last_scan_summary":CANDLE+" / WAIT / CANDIDATE_METHOD=WAIT — "+
                                "BRAK ZATWIERDZONEJ METODY / QUEUE=NO / "+
                                "GATES=OK",
        },
        "last_vote_audit":{
            "candle_utc":CANDLE,"epic":"US500",
            "source":"Capital.com DEMO REST",
            "mode":"AUTO — 6 STRATEGII","decision":"WAIT",
            "rows":rows,"progress":stages,
            "watch":{"side":"WAIT","score":2,
                     "reason":"Za mało przewagi na M1"},
        }
    }


def test_six_waits_and_no_invented_direction_or_price():
    radar=worker_signal_radar(fixture(),now=NOW)
    assert radar["current"] and len(radar["rows"])==6
    assert (radar["raw_long"],radar["raw_short"],
            radar["mtf_long"],radar["mtf_short"],radar["veto"])==(0,0,0,0,0)
    assert radar["watch"]["side"]=="WAIT"
    assert all(r["Etap"]=="0/3" and r["Obserwuj"]=="BRAK" for r in radar["rows"])
    assert all(r["Brakuje"]=="Trend" for r in radar["rows"])
    assert all(r["Po MTF"]=="WAIT" for r in radar["rows"])
    assert radar["is_trade_instruction"] is False
    assert not any("entry" in r or "SL" in r or "TP" in r for r in radar["rows"])


def test_watch_is_not_approved_paper_and_stage_not_probability():
    data=fixture()
    data["last_vote_audit"]["watch"]={
        "side":"LONG","score":4,"reason":"Momentum wzrostowe M1"}
    progress=data["last_vote_audit"]["progress"][0]
    progress["stage"]=2
    progress["side"]="LONG"
    progress["criteria"][0]["ok"]=True
    progress["criteria"][1]["ok"]=True
    radar=worker_signal_radar(data,now=NOW)
    assert radar["watch"]["side"]=="LONG"
    assert radar["mtf_long"]==0 and radar["raw_long"]==0
    assert radar["rows"][0]["Etap"]=="2/3"
    assert radar["rows"][0]["Obserwuj"]=="LONG"
    assert radar["rows"][0]["Setup OHLC"]=="WAIT"


def test_mtf_veto_keeps_raw_short_separate_from_paper():
    data=fixture()
    data["last_vote_audit"]["rows"][0].update(
        raw="SHORT",after_mtf="WAIT",reason="MTF_NOT_READY")
    data["last_vote_audit"]["progress"][0].update(
        stage=2,side="SHORT")
    radar=worker_signal_radar(data,now=NOW)
    assert radar["raw_short"]==1 and radar["mtf_short"]==0
    assert radar["veto"]==1 and not radar["conflict"]
    assert radar["rows"][0]["Dlaczego"]=="MTF_NOT_READY"


def test_opposite_raw_votes_are_marked_as_conflict():
    data=fixture()
    data["last_vote_audit"]["rows"][0]["raw"]="SHORT"
    data["last_vote_audit"]["rows"][1]["raw"]="LONG"
    radar=worker_signal_radar(data,now=NOW)
    assert radar["conflict"]
    assert radar["raw_long"]==1 and radar["raw_short"]==1


def test_audit_from_previous_candle_cannot_be_current_even_with_fresh_meta():
    data=fixture()
    data["meta"]["last_scan_summary"]=(
        "WAIT / DATA_STALE / QUEUE=NO / ACTIVE=NONE")
    result=worker_signal_radar(data,now=NOW)
    assert not result["current"]
    assert result["rows"]==[]
    assert result["reason"]=="GŁOSY_Z_POPRZEDNIEGO_SKANU"


def test_old_scan_or_future_clock_does_not_expose_live_candidates():
    data=fixture()
    for now in ("2026-11-17T14:30:00+00:00",
                "2026-11-17T14:10:01+00:00"):
        result=worker_signal_radar(data,now=now)
        assert result["current"] is False
        assert result["rows"]==[]


def test_wrong_broker_strategy_epic_partial_and_missing_audits_fail_closed():
    for field,value in (("source","CSV"),("epic","GER40"),
                        ("strategy","EMA TREND")):
        data=fixture()
        data["meta"][field]=value
        result=worker_signal_radar(data,now=NOW)
        assert result["rows"]==[] and not result["current"]
    data=fixture()
    data["last_vote_audit"]["rows"].pop()
    assert not worker_signal_radar(data,now=NOW)["current"]
    for payload in ({},{"meta":{}},None):
        assert not worker_signal_radar(payload,now=NOW)["current"]


def test_unknown_observation_side_and_bad_stage_dont_create_long_short():
    data=fixture()
    data["last_vote_audit"]["progress"][0]["side"]="BUY IMMEDIATELY"
    data["last_vote_audit"]["progress"][0]["stage"]=300
    data["last_vote_audit"]["watch"]["side"]="BUY"
    data["last_vote_audit"]["watch"]["score"]=200
    out=worker_signal_radar(data,now=NOW)
    assert out["current"]
    assert out["rows"][0]["Obserwuj"]=="BRAK"
    assert out["rows"][0]["Etap"]=="BRAK"
    assert out["watch"]["side"]=="WAIT"
    assert out["watch"]["score"] is None


def test_presentation_is_read_only_and_reuses_existing_checkpoint():
    code=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    radar=Path("trader/cloud_signal_radar.py").read_text(encoding="utf8")
    assert "radar=worker_signal_radar(payload)" in code
    assert 'st.dataframe(pd.DataFrame(radar["rows"])' in code
    assert "queue_paper(" not in code+radar
    assert "CapitalReadOnly(" not in code+radar
    assert "requests." not in radar
    assert "supabase" not in radar.lower()
