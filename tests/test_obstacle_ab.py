"""Read-only obstacle audit: not a new trading policy or Claude-generated order."""
from datetime import datetime,timezone
from types import SimpleNamespace
from pathlib import Path
import pandas as pd

from trader import obstacle_ab as lab
from trader.candidate_radar import append_candidate
from trader.strategy import Decision


def frame():
    idx=pd.date_range("2026-11-17T20:00Z",periods=90,freq="min")
    return pd.DataFrame({"Open":[100]*90,"High":[101]*90,
                         "Low":[99]*90,"Close":[100]*90},index=idx)


def views(*,h1="NEUTRAL",ready=True):
    return [SimpleNamespace(timeframe=name,ready=ready,trend=trend)
            for name,trend in (("MINUTE","UP"),("MINUTE_5","UP"),
                               ("MINUTE_15","UP"),("HOUR",h1))]


def fake_decide(data,method,*,spread,obstacle_mode):
    if method=="EMA TREND":
        if obstacle_mode=="legacy":
            return Decision("WAIT",method,"Zbyt bliski opór")
        return Decision("LONG",method,"Trend EMA",entry=100,stop=98,
                        target=104,rr=1.4)
    return Decision("WAIT",method,"Brak pełnego setupu.")


def test_same_closed_candle_unlocks_only_hypothetical_swing(monkeypatch):
    monkeypatch.setattr(lab,"decide_any",fake_decide)
    result=lab.obstacle_ab_snapshot(frame(),.6,views())
    assert result["status"]=="OK"
    assert result["mtf"]=="UP"
    assert result["research_only"] is True
    assert len(result["rows"])==2
    a=result["rows"][0]
    assert a["strategy"]=="EMA TREND"
    assert a["legacy"]=="WAIT" and a["swing"]=="LONG"
    assert a["swing_after_mtf"]=="LONG"
    assert a["swing_unlocked"] and a["legacy_room_veto"]
    assert a["NOT_PAPER"] is True
    assert a["all_worker_gates_clear"] is True
    assert a["swing_rr"]==1.4
    assert result["rows"][1]["swing_unlocked"] is False


def test_mtf_opposition_and_missing_data_do_not_claim_approved(monkeypatch):
    monkeypatch.setattr(lab,"decide_any",fake_decide)
    for tfviews in (views(h1="DOWN"),views(ready=False),[]):
        out=lab.obstacle_ab_snapshot(frame(),.6,tfviews)
        a=out["rows"][0]
        assert a["swing"]=="LONG"
        assert a["swing_after_mtf"]=="WAIT"
        assert a["swing_rr"] is None


def test_global_blockers_do_not_allow_new_paper(monkeypatch):
    monkeypatch.setattr(lab,"decide_any",fake_decide)
    result=lab.obstacle_ab_snapshot(frame(),.6,views(),blockers=["MACRO_BLACKOUT"])
    a=result["rows"][0]
    assert a["swing_unlocked"]
    assert a["swing_after_mtf"]=="LONG"
    assert a["all_worker_gates_clear"] is False


def test_invalid_source_avoids_any_alt_signal(monkeypatch):
    monkeypatch.setattr(lab,"decide_any",fake_decide)
    for source,epic in (("CSV","US500"),(lab.SOURCE,"GER40")):
        out=lab.obstacle_ab_snapshot(frame(),.6,views(),source=source,epic=epic)
        assert out["status"]=="UNVERIFIED" and out["rows"]==[]
    assert lab.obstacle_ab_snapshot(frame().iloc[:50],.6,views())["rows"]==[]


def test_forward_only_candidate_archive_and_rolling_count(monkeypatch):
    monkeypatch.setattr(lab,"decide_any",fake_decide)
    f=frame()
    snap=SimpleNamespace(source=lab.SOURCE,epic="US500",
                         resolution="MINUTE",confirmed_utc=f.index[-1])
    ab=lab.obstacle_ab_snapshot(f,.6,views())
    hist=append_candidate([],snap,Decision("WAIT","AUTO","none"),[],[],
                          obstacle_ab=ab)
    totals=lab.obstacle_ab_frequencies(hist)
    assert totals["audited_scans"]==1
    a=totals["rows"][0]
    assert a["scans"]==1
    assert a["legacy_room_veto"]==1
    assert a["swing_unlocked_raw"]==1
    assert a["swing_after_mtf"]==1
    assert a["swing_with_all_gates"]==1
    # No duplicate count for same checkpoint and previous entries with no audit.
    assert lab.obstacle_ab_frequencies(hist+hist)["audited_scans"]==1
    assert lab.obstacle_ab_frequencies([{"key":"old","candle_utc":"nope"}])["audited_scans"]==0
    corrupt={**hist[0],"obstacle_ab":{**ab,"candle_utc":"2026-01-01T01:01Z"}}
    assert lab.obstacle_ab_frequencies([corrupt])["audited_scans"]==0


def test_cloud_ui_and_worker_are_isolated_from_actual_trade_path():
    ui=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    app=Path("app.py").read_text("utf8")
    worker=Path("trader/worker.py").read_text("utf8")
    core=Path("trader/obstacle_ab.py").read_text("utf8")
    assert "FILTR OPORU: STARY vs POTWIERDZONE SWINGI" in ui
    assert "PORÓWNANIE POZIOMÓW — EMA LEGACY vs SWING" in app
    assert 'vote_audit["obstacle_ab"]=obstacle_ab_snapshot(' in worker
    assert "queue_paper(" not in core
    assert "CapitalReadOnly(" not in core
    assert "execute_order" not in core
    assert 'obstacle_mode="legacy"' in core
    assert 'obstacle_mode="confirmed_swings"' in core
