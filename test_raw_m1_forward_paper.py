"""Forward M1 RAW test: signals vetoed by MTF become testable virtual entries."""
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import pytest

from trader.raw_m1_forward_paper import advance_raw_paper,raw_paper_report,blank
from trader.raw_paper_chart import annotate_raw_forward,rows_for_journal


def candles(count=95, *, side="LONG"):
    index=pd.date_range("2026-11-17T19:00:00Z",periods=count,freq="min")
    prices=[7400+(i*.10 if side=="LONG" else -i*.10) for i in range(count)]
    return pd.DataFrame({
        "Open":prices,
        "High":[v+1.2 for v in prices],
        "Low":[v-1.2 for v in prices],
        "Close":prices,"Spread":[.4]*count},index=index)


def votes(side="LONG",mtf="WAIT"):
    return [
        {"Strategia":"EMA TREND","Setup OHLC":side,
         "Po filtrze MTF":mtf,"Powód":"MTF veto"},
        {"Strategia":"EMA PULLBACK","Setup OHLC":"WAIT",
         "Po filtrze MTF":"WAIT"},
    ]


def test_actual_raw_long_vetoed_by_mtf_opens_next_bar_not_hindsight():
    data=candles()
    state=advance_raw_paper({},data,votes(),spread=.4)
    assert state["started"]==1
    assert state["opened"]==0
    assert state["active"]["status"]=="PENDING"
    assert state["active"]["after_mtf"]==[]
    assert state["active"]["side"]=="LONG"
    assert state["active"]["methods"]==["EMA TREND"]

    more=candles(96)
    state=advance_raw_paper(state,more,votes(),spread=.4)
    assert state["opened"]==1
    assert state["active"]["status"]=="OPEN"
    assert state["active"]["entry_bar_open_utc"]==more.index[-2].isoformat()
    assert state["active"]["opened_utc"]==more.index[-1].isoformat()
    assert state["active"]["entry_exec"]>state["active"]["entry_mid"]
    assert state["active"]["entry_signal"]!=0

    # exactly idempotent: worker repeats the same closed candle
    duplicate=advance_raw_paper(state,more,votes(),spread=.4)
    assert duplicate["opened"]==state["opened"]
    assert duplicate["active"]["bars_held"]==state["active"]["bars_held"]

    next_c=candles(97)
    next_c.iloc[-1,next_c.columns.get_loc("High")]=state["active"]["target"]+.3
    next_c.iloc[-1,next_c.columns.get_loc("Low")]=state["active"]["stop"]+.3
    done=advance_raw_paper(state,next_c,votes(),spread=.4)
    assert done["active"] is None
    assert done["closed"][0]["status"]=="CLOSED_TP"
    assert done["closed"][0]["pnl_pts"]>0
    assert done["opened"]==1
    r=raw_paper_report(done)
    assert r["closed"]==1
    assert r["started"]==1
    assert r["win_rate_pct"]==100
    assert r["no_broker_orders"] is True
    assert r["recent"][0]["entry_bar_open_utc"]==more.index[-2].isoformat()


def test_raw_short_vetoed_by_mtf_still_qualifies_and_stop_is_first():
    one=candles(side="SHORT")
    state=advance_raw_paper({},one,votes("SHORT"),spread=.4)
    assert state["active"]["side"]=="SHORT"
    assert state["active"]["target"]<state["active"]["entry_signal"]<state["active"]["stop"]
    second=candles(96,side="SHORT")
    second.iloc[-1,second.columns.get_loc("High")]=state["active"]["stop"]+.7
    second.iloc[-1,second.columns.get_loc("Low")]=state["active"]["target"]-.7
    done=advance_raw_paper(state,second,votes("SHORT"),spread=.4)
    assert done["active"] is None
    assert done["closed"][0]["status"]=="CLOSED_SL"
    assert done["closed"][0]["pnl_pts"]<0


@pytest.mark.parametrize("veto",[
    [{"Strategia":"EMA TREND","Setup OHLC":"WAIT","Po filtrze MTF":"WAIT"}],
    [*votes("LONG"),*votes("SHORT")],
])
def test_no_raw_or_conflicting_raw_never_opens(veto):
    result=advance_raw_paper({},candles(),veto,spread=.4)
    assert result["started"]==0 and result["active"] is None


@pytest.mark.parametrize("blocker",[
    "DATA_STALE","MARKET_NOT_TRADEABLE","INCOMPLETE_MTF",
    "MACRO_BLACKOUT","SETUPS_DISABLED","PAPER_DAILY_STOP",
])
def test_global_guards_remain_mandatory(blocker):
    result=advance_raw_paper({},candles(),votes(),[blocker],spread=.4)
    assert result["started"]==0
    assert result["active"] is None
    assert blocker in result["last_reason"]


def test_data_gap_invalidates_pending_without_fake_fill_and_no_backfill():
    first=advance_raw_paper({},candles(),votes(),spread=.4)
    # Real hole: minute 95 is absent from the snapshot, so nothing to replay.
    jumped=advance_raw_paper(first,candles(97).drop(candles(97).index[95]),votes(),spread=.4)
    assert jumped["gaps"]==1
    assert jumped["invalidated"]==1
    assert jumped["active"] is None
    assert jumped["opened"]==0


def test_broker_live_and_invalid_data_never_create_paper_positions():
    assert advance_raw_paper({},candles(),votes(),spread=.4,
                             source="Capital.com LIVE REST")["started"]==0
    assert advance_raw_paper({},candles(),votes(),spread=float("nan"))["started"]==0
    bad=candles()
    bad.iloc[-1,bad.columns.get_loc("Low")]=1e5
    assert advance_raw_paper({},bad,votes(),spread=.4)["started"]==0
    off=advance_raw_paper({},candles(),votes(),spread=.4,enabled=False)
    assert off["started"]==0 and off["last_reason"]=="RAW_TEST_WYLACZONY"


def test_daily_limit_tracks_attempts_even_when_invalidated():
    first=candles()
    day=str(first.index[-1].date())
    x=blank()
    x["attempted_per_utc_day"]={day:12}
    result=advance_raw_paper(x,first,votes(),spread=.4)
    assert result["active"] is None and result["started"]==0
    assert "MAX_12" in result["last_reason"]


def test_plotting_is_read_only_and_markers_come_only_from_ledger():
    beginning=candles()
    one=advance_raw_paper({},beginning,votes(),spread=.4)
    two=advance_raw_paper(one,candles(96),votes(),spread=.4)
    report=raw_paper_report(two)
    empty=go.Figure()
    annotate_raw_forward(empty,{"status":"FORWARD_ONLY_RAW_M1_SIMULATION",
                                "active":None,"recent":[]})
    assert len(empty.data)==0
    fig=go.Figure()
    annotate_raw_forward(fig,report)
    assert len(fig.data)>=1
    assert any("RAW TEST OPEN LONG" in trace.name for trace in fig.data)
    assert len(fig.layout.shapes)>=3   # actual trade's entry, stop, target
    assert "OTWARCIE" not in str(report["active"].get("status"))
    assert "OPEN" in rows_for_journal(report)[0]["Status"]
    assert rows_for_journal(report)[0]["SETUP (Polska)"].startswith("17.11.2026")
    # Replay of old raw data must not be incorrectly claimed as executed
    no=raw_paper_report(blank())
    assert rows_for_journal(no)==[]


def test_worker_and_cloud_chart_both_read_real_persisted_raw_report():
    worker=Path("trader/worker.py").read_text(encoding="utf8")
    screen=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    engine=Path("trader/raw_m1_forward_paper.py").read_text(encoding="utf8")
    chart=Path("trader/raw_paper_chart.py").read_text(encoding="utf8")
    assert "advance_raw_paper(" in worker
    assert 'payload["raw_m1_forward_paper_report"]' in worker
    assert "annotate_raw_forward(candles,raw_trial," in screen
    assert "with live_chart_slot.container()" in screen
    assert "rows_for_journal(raw_trial" in screen
    assert "queue_paper(" not in engine and "POST /positions" not in engine
    assert "CapitalReadOnly(" not in engine
    assert "session.post(" not in engine and "session.post(" not in chart
    assert "for i in range" not in engine  # no historical replay loop
