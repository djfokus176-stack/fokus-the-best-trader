"""Causal offline regression of forward MTF passed/vetoed SHADOW research."""
import pandas as pd
import pytest
from pathlib import Path
from trader import mtf_veto_forward as mtf
from trader.strategy import Decision


def bars(count=85):
    idx=pd.date_range("2026-11-17T12:00:00Z",periods=count,freq="min")
    return pd.DataFrame({"Open":[100.]*count,
                         "High":[100.25]*count,
                         "Low":[99.75]*count,
                         "Close":[100.]*count},index=idx)


def vote(name="EMA TREND",side="LONG",after="WAIT"):
    return [{"Strategia":name,"Setup OHLC":side,
             "Po filtrze MTF":after,"Powód":"MTF"}]


def stub(frame,name,spread):
    return Decision("LONG",name,"test closed bars",entry=100,
                    stop=99,target=102,rr=1.3)


def test_forward_vetoed_signal_is_tracked_but_not_paper(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    base=bars()
    state=mtf.advance_mtf_comparison({},base,vote(),[],spread=.6)
    assert state["started"]==1
    assert len(state["active"])==1
    assert state["active"]["EMA TREND"]["mtf"]=="VETOED"
    # Same closed bar must never trigger a synthetic fill or duplicated setup.
    same=mtf.advance_mtf_comparison(state,base,vote(),[],spread=.6)
    assert same["started"]==1 and len(same["closed"])==0
    # Next closed bar reveals a hypothetical open at 100; touches TP.
    next_bar=bars(86)
    next_bar.iloc[-1,next_bar.columns.get_loc("High")]=102.5
    settled=mtf.advance_mtf_comparison(state,next_bar,[],[],spread=.6)
    assert len(settled["closed"])==1
    record=settled["closed"][0]
    assert record["mtf"]=="VETOED" and record["exit"]=="TP"
    assert record["pnl_pts"]==pytest.approx(.90)
    assert record["bars"]==1 and record["slippage_per_side"]==.25
    assert len(settled["active"])==0
    summary=mtf.mtf_comparison_report(settled)
    veto=next(v for v in summary["groups"]
              if v["strategy"]=="ALL" and v["mtf"]=="VETOED")
    passed=next(v for v in summary["groups"]
                if v["strategy"]=="ALL" and v["mtf"]=="PASSED")
    assert veto["closed"]==1 and veto["sum_pts"]==.9
    assert passed["closed"]==0 and passed["sum_pts"] is None


def test_identical_passed_setup_uses_identical_fills(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    original=bars()
    state=mtf.advance_mtf_comparison({},original,vote(after="LONG"),[],spread=.6)
    target=bars(86)
    target.iloc[-1,target.columns.get_loc("High")]=102.5
    state=mtf.advance_mtf_comparison(state,target,[],[],spread=.6)
    assert state["closed"][0]["mtf"]=="PASSED"
    assert state["closed"][0]["pnl_pts"]==pytest.approx(.9)


def test_both_sl_and_tp_touched_in_same_bar_sl_wins(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    state=mtf.advance_mtf_comparison({},bars(),vote(),[],spread=.6)
    candle=bars(86)
    candle.iloc[-1,candle.columns.get_loc("High")]=102.5
    candle.iloc[-1,candle.columns.get_loc("Low")]=98.5
    state=mtf.advance_mtf_comparison(state,candle,[],[],spread=.6)
    assert state["closed"][0]["exit"]=="SL"
    assert state["closed"][0]["pnl_pts"]==pytest.approx(-2.10)


def test_no_open_from_early_watch_or_stage_two(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    frame=bars()
    data=mtf.advance_mtf_comparison({},frame,[
        {"Strategia":"EMA TREND","Setup OHLC":"WAIT",
         "Po filtrze MTF":"WAIT","Etap":"2/3","Obserwuj":"LONG"},
    ],[],spread=.6)
    assert data["started"]==0 and data["active"]=={}


def test_global_blockers_and_conflicting_raw_sides_fail_closed(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    raw=bars()
    state=mtf.advance_mtf_comparison({},raw,vote(),["MACRO_BLACKOUT"],spread=.6)
    assert state["started"]==0 and state["skipped_blocked"]==1
    mixed=vote()+vote(name="LIQUIDITY SWEEP",side="SHORT")
    state=mtf.advance_mtf_comparison({},raw,mixed,[],spread=.6)
    assert state["started"]==0


def test_candle_gap_invalidates_instead_of_backfilling(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    data=mtf.advance_mtf_comparison({},bars(),vote(),[],spread=.6)
    miss=bars(87) # newest closed t+2, but t+1 was never observed
    data=mtf.advance_mtf_comparison(data,miss,vote(),[],spread=.6)
    assert data["gaps"]==1 and data["invalidated"]==1
    assert data["started"]==1 and not data["active"]
    assert not data["closed"]


def test_timeout_after_twenty_consecutive_closed_minutes(monkeypatch):
    monkeypatch.setattr(mtf,"decide_any",stub)
    data=mtf.advance_mtf_comparison({},bars(),vote(),[],spread=.6)
    for i in range(86,106):
        data=mtf.advance_mtf_comparison(data,bars(i),[],[],spread=.6)
    assert data["closed"][0]["exit"]=="TIMEOUT"
    assert data["closed"][0]["bars"]==20
    assert data["closed"][0]["pnl_pts"]==pytest.approx(-1.10)


def test_wrong_source_and_invalid_spread_do_not_create_research():
    assert mtf.advance_mtf_comparison({},bars(),vote(),[],
             spread=.6,source="Capital.com LIVE REST")==mtf._new()
    assert mtf.advance_mtf_comparison({},bars(),vote(),[],
             spread=float("nan"))==mtf._new()


def test_worker_and_ui_only_persist_research_never_touches_real_paper():
    worker=Path("trader/worker.py").read_text(encoding="utf8")
    app=Path("app.py").read_text(encoding="utf8")
    research=Path("trader/mtf_veto_forward.py").read_text(encoding="utf8")
    assert "mtf_veto_state=advance_mtf_comparison(" in worker
    assert 'payload["mtf_veto_forward"]=' in worker
    assert "🧪 MTF — CZY ODRZUCONE WEJŚCIA BYŁY LEPSZE?" in app
    assert "queue_paper(" not in research
    assert "CapitalReadOnly(" not in research
    assert "filter_mtf_decision(" not in research
    assert "execute_order" not in research
