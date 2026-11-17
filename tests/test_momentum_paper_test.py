"""Offline proof that TEST approvals never become real broker/PAPER v3 orders."""
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from trader import momentum_paper_test as lab
from trader.early_watch import Watch


def frame(count=90, *, down=False):
    idx = pd.date_range("2026-11-17T12:00:00Z",periods=count,freq="min")
    vals = [110-i*.07 if down else 100+i*.07 for i in range(count)]
    return pd.DataFrame({
        "Open": vals,
        "High": [v+.72 for v in vals],
        "Low": [v-.72 for v in vals],
        "Close": vals,
        "Spread": [.30]*count,
    },index=idx)


def progress(side="LONG",stage=2):
    return [
        {"strategy":"EMA TREND","side":side,"stage":stage},
        {"strategy":"EMA PULLBACK","side":side,"stage":stage},
    ]


def views(m5="UP",m15="UP",good=True):
    return [
        SimpleNamespace(timeframe="MINUTE",ready=good,trend="UP"),
        SimpleNamespace(timeframe="MINUTE_5",ready=good,trend=m5),
        SimpleNamespace(timeframe="MINUTE_15",ready=good,trend=m15),
        SimpleNamespace(timeframe="HOUR",ready=good,trend="DOWN"),
    ]


def set_watch(monkeypatch,side="LONG",score=6,countertrend=False):
    monkeypatch.setattr(lab,"evaluate_early_watch",
        lambda frame:Watch(side,score,countertrend,
                           "Weryfikacja M1",frame.index[-1]))


def test_real_2of3_creates_independent_test_pending_without_paper_v3(monkeypatch):
    set_watch(monkeypatch)
    s=lab.advance_momentum_paper_test({},frame(),progress(),views(),
                                      spread=.3)
    assert s["started"]==1 and s["opened"]==0
    assert s["active"]["status"]=="PENDING"
    assert s["active"]["side"]=="LONG"
    assert s["active"]["score"]==6
    assert s["active"]["target"]>s["active"]["entry_signal"]>s["active"]["stop"]
    assert s["last_reason"]=="TEST_SETUP_ZATWIERDZONY_LONG"
    report=lab.momentum_paper_test_report(s)
    assert report["pending"] and report["no_real_orders"]
    assert report["closed"]==0


def test_next_closed_bar_opens_and_later_closes_with_costs(monkeypatch):
    set_watch(monkeypatch)
    a=lab.advance_momentum_paper_test({},frame(),progress(),views(),spread=.3)
    b=frame(91)
    b.iloc[-1,b.columns.get_loc("High")] = float(a["active"]["target"])-.3
    b.iloc[-1,b.columns.get_loc("Low")] = float(a["active"]["stop"])+.3
    a=lab.advance_momentum_paper_test(a,b,progress(),views(),spread=.3)
    assert a["active"]["status"]=="OPEN"
    assert a["opened"]==1
    assert a["active"]["bars_held"]==1
    assert a["last_reason"]=="TEST_OPEN_LONG"
    # Must not double-fill when worker repeats the same closed candle.
    same=lab.advance_momentum_paper_test(a,b,progress(),views(),spread=.3)
    assert same["opened"]==1 and same["active"]["bars_held"]==1
    c=frame(92)
    c.iloc[-1,c.columns.get_loc("High")] = a["active"]["target"]+.25
    c.iloc[-1,c.columns.get_loc("Low")] = a["active"]["stop"]+.30
    closed=lab.advance_momentum_paper_test(a,c,progress(),views(),spread=.3)
    assert closed["active"] is None
    assert len(closed["closed"])==1
    trade=closed["closed"][0]
    assert trade["status"]=="CLOSED_TP" and trade["pnl_pts"]>0
    assert closed["opened"]==1 and closed["started"]==1
    assert lab.momentum_paper_test_report(closed)["closed"]==1
    assert lab.momentum_paper_test_report(closed)["win_rate_pct"]==100


def test_stop_first_if_bar_crosses_both_tp_and_sl(monkeypatch):
    set_watch(monkeypatch)
    state=lab.advance_momentum_paper_test({},frame(),progress(),views(),spread=.30)
    f=frame(91)
    f.iloc[-1,f.columns.get_loc("High")]=state["active"]["target"]+.5
    f.iloc[-1,f.columns.get_loc("Low")]=state["active"]["stop"]-.5
    ended=lab.advance_momentum_paper_test(state,f,progress(),views(),spread=.30)
    assert ended["active"] is None
    assert ended["opened"]==1
    assert ended["closed"][0]["status"]=="CLOSED_SL"
    assert ended["closed"][0]["pnl_pts"]<0


def test_short_direction_is_real_candidate_with_geometry(monkeypatch):
    set_watch(monkeypatch,"SHORT",6)
    result=lab.advance_momentum_paper_test({},frame(down=True),
         progress("SHORT"),views("DOWN","NEUTRAL"),spread=.30)
    assert result["active"]["side"]=="SHORT"
    assert result["active"]["target"]<result["active"]["entry_signal"]<result["active"]["stop"]


@pytest.mark.parametrize("side,score,counter,stages,m5,m15,blocked",[
    ("LONG",4,False,2,"UP","UP",False),
    ("LONG",6,True,2,"UP","UP",False),
    ("LONG",6,False,1,"UP","UP",False),
    ("LONG",6,False,2,"DOWN","UP",False),
    ("LONG",6,False,2,"UP","DOWN",False),
    ("LONG",6,False,2,"UP","UP",True),
])
def test_safety_vetoes_are_kept(monkeypatch,side,score,counter,stages,m5,m15,blocked):
    set_watch(monkeypatch,side,score,counter)
    data=lab.advance_momentum_paper_test(
        {},frame(),progress(stage=stages),views(m5,m15),
        ["MACRO_BLACKOUT"] if blocked else [],spread=.3)
    assert data["active"] is None
    assert data["started"]==0


def test_source_market_and_data_gaps_fail_closed(monkeypatch):
    set_watch(monkeypatch)
    assert lab.advance_momentum_paper_test(
        {},frame(),progress(),views(),spread=.3,source="Capital.com LIVE REST")["started"]==0
    invalid=frame()
    invalid.iloc[-1,invalid.columns.get_loc("High")]=0
    assert lab.advance_momentum_paper_test(
        {},invalid,progress(),views(),spread=.3)["started"]==0
    assert lab.advance_momentum_paper_test(
        {},frame(),progress(),views(),spread=float("nan"))["started"]==0
    first=lab.advance_momentum_paper_test(
        {},frame(),progress(),views(),spread=.3)
    # No worker invocation at next minute despite it being in the broker frame.
    missed=lab.advance_momentum_paper_test(
        first,frame(92),progress(),views(),spread=.3)
    assert missed["gaps"]==1 and missed["invalidated"]==1
    assert missed["active"] is None and missed["started"]==1


def test_daily_trial_cap_and_recent_trade_window(monkeypatch):
    set_watch(monkeypatch)
    earlier=frame()
    daily=earlier.index[-1].strftime("%Y-%m-%d")
    state=lab.blank()
    state["closed"]=[{
       "setup_utc":daily+"T12:00:00+00:00","side":"LONG",
       "status":"CLOSED_TP","pnl_pts":1.0,
    } for _ in range(8)]
    x=lab.advance_momentum_paper_test(
        state,earlier,progress(),views(),spread=.3)
    assert x["started"]==0 and x["last_reason"]=="DZIENNY_LIMIT_TEST_8"


def test_research_implementation_does_not_touch_existing_paper_v3():
    source=Path("trader/momentum_paper_test.py").read_text("utf8")
    worker=Path("trader/worker.py").read_text("utf8")
    ui=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    assert "advance_momentum_paper_test(" in worker
    assert "payload[\"momentum_paper_test\"]=" in worker
    assert "PAPER TEST — WCZEŚNIEJSZE LONG / SHORT" in ui
    assert "queue_paper(" not in source
    assert "CapitalReadOnly(" not in source
    assert "paper_positions_v3" not in source
    assert "execute_order" not in source
    assert "MIN_SCORE = 5" in source
