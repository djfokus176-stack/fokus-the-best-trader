"""Causal long/short three-wave research, non-trading and forward archival."""
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import pytest

from trader.fokus_3f import (
    NAME, current_3f_research, run_3f_replay,
    research_scorecard, RESOLVED,
)
from trader.fokus_3f_forward import (
    advance_3f_forward, forward_3f_scorecard,
)
from trader.auto_strategy import AUTO_MODE
from trader.strategies_pro import ALL_STRATEGIES


def synthetic(side="SHORT", *, next_bar=True):
    """Closed M15 CASH candles across four dates; three same-day pivots."""
    days=("2026-11-09","2026-11-10","2026-11-11","2026-11-12")
    stamps=[]
    for day in days:
        stamps.extend(pd.date_range(f"{day} 09:45",periods=26,
            freq="15min",tz="America/New_York").tz_convert("UTC"))
    close=[100.]*len(stamps)
    op=[100.]*len(stamps)
    high=[101.]*len(stamps)
    low=[99.]*len(stamps)
    day_start=26*3
    for k in (4,9,14):
        if side=="SHORT":
            high[day_start+k]=108.
        else:
            low[day_start+k]=90.
    sig=day_start+17
    if side=="SHORT":
        close[sig]=97.
        high[sig]=101.
        low[sig]=96.
        if next_bar:
            op[sig+1]=97.
            close[sig+1]=100.
            high[sig+1]=115.  # stop reached
            low[sig+1]=65.    # target reached too; SL FIRST
    else:
        close[sig]=103.
        high[sig]=104.
        low[sig]=99.
        if next_bar:
            op[sig+1]=103.
            close[sig+1]=100.
            high[sig+1]=150.
            low[sig+1]=85.
    frame=pd.DataFrame({"Open":op,"High":high,"Low":low,
                        "Close":close,"Spread":[.6]*len(stamps)},
                       index=pd.DatetimeIndex(stamps))
    return frame, sig


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_three_confirmed_pivots_emit_only_closed_asof_research(side):
    frame,i=synthetic(side)
    assert current_3f_research(frame.iloc[:i])["research_side"]=="WAIT"
    new=current_3f_research(frame.iloc[:i+1])
    assert new["research_side"]==side
    assert new["trade_permission"]=="WAIT"
    assert new["strategy"]==NAME
    assert new["rr_gross"]==1.8
    assert new["signal_index"]==i
    assert new["pivot3_utc"]<new["signal_utc"]
    assert "action" not in new
    assert "broker_order" not in new
    assert "entry_executable" not in new


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_replay_enters_next_bar_and_conservatively_hits_sl_first(side):
    frame,i=synthetic(side)
    trades=run_3f_replay(frame)
    assert len(trades)==1
    row=trades.iloc[0]
    assert row.research_side==side
    assert row.status=="SL"
    assert row.pnl_pts<0
    assert row.entry_utc==frame.index[i+1].isoformat()
    assert row.signal_utc==frame.index[i].isoformat()
    assert row.entry_executable!=row.entry_mid
    assert row.trade_permission=="WAIT"
    assert research_scorecard(trades)[0 if side=="LONG" else 1]["closed"]==1


def test_missing_future_never_books_a_fake_win():
    frame,i=synthetic("SHORT")
    report=run_3f_replay(frame.iloc[:i+1])
    assert len(report)==1
    assert report.iloc[0].status=="PENDING_NEXT_BAR"
    assert pd.isna(report.iloc[0].pnl_pts)
    assert research_scorecard(report)[1]["net_pts"] is None


def test_future_or_removed_bar_cannot_retroactively_change_setup():
    frame,i=synthetic("SHORT")
    initial=current_3f_research(frame.iloc[:i+1])
    modified=frame.copy()
    modified.iloc[i+1,modified.columns.get_loc("High")]=1000.
    assert current_3f_research(modified.iloc[:i+1])==initial
    deleted=frame.drop(frame.index[i-5])  # broken M15 session
    assert current_3f_research(deleted.iloc[:i])["research_side"]=="WAIT"


def test_bad_recorded_spread_or_non_m15_fails_closed():
    frame,i=synthetic("SHORT")
    frame.loc[frame.index[i],"Spread"]=-1.
    with pytest.raises(ValueError):
        current_3f_research(frame.iloc[:i+1])
    good,_=synthetic()
    with pytest.raises(ValueError):
        current_3f_research(good.iloc[-30:])
    wrong=good.copy()
    wrong.index=wrong.index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError):
        run_3f_replay(wrong)


def test_forward_first_priming_and_subsequent_closed_pnl_is_immutable():
    frame,i=synthetic("SHORT")
    state=advance_3f_forward(None,frame.iloc[:i])
    assert state["events"]==[]
    assert state["status"]=="PRIMED_NO_HISTORICAL_BACKFILL"
    state=advance_3f_forward(state,frame.iloc[:i+1])
    assert len(state["events"])==1
    assert state["events"][0]["research_side"]=="SHORT"
    assert state["events"][0]["status"]=="PENDING_NEXT_BAR"
    assert state["trade_permission"]=="WAIT"
    again=advance_3f_forward(state,frame.iloc[:i+1])
    assert again==state
    resolved=advance_3f_forward(state,frame.iloc[:i+2])
    assert resolved["events"][0]["status"]=="SL"
    assert resolved["events"][0]["pnl_pts"]<0
    assert forward_3f_scorecard(resolved)["independent_oos_verified"] is False
    assert forward_3f_scorecard(resolved)["trade_permission"]=="WAIT"
    altered=frame.copy()
    altered.iloc[i+1,altered.columns.get_loc("High")]=101.
    altered.iloc[i+1,altered.columns.get_loc("Low")]=96.
    frozen=advance_3f_forward(resolved,altered.iloc[:i+3])
    assert frozen["events"][0]["pnl_pts"]==resolved["events"][0]["pnl_pts"]


def test_no_historical_retrofit_on_multi_bar_reconnect():
    frame,i=synthetic("LONG")
    state=advance_3f_forward(None,frame.iloc[:i-1])
    skipped=advance_3f_forward(state,frame.iloc[:i+1])
    assert skipped["events"]==[]
    assert skipped["status"]=="RECONNECTED_OR_GAPPED_NO_NEW_FORWARD"


def test_auto_and_paper_entry_surfaces_unchanged():
    from trader.paper_method_labels import RESEARCH_DISPLAY_ORDER
    assert RESEARCH_DISPLAY_ORDER[0]==AUTO_MODE
    assert RESEARCH_DISPLAY_ORDER[-1]==NAME
    assert NAME not in ALL_STRATEGIES
    # An independent research output cannot be fed to the PAPER Decision
    # object protocol; it has research_side, not action, entry or stop.
    signal=current_3f_research(synthetic("LONG")[0].iloc[:96])
    assert "action" not in signal
    assert "entry" not in signal
    assert signal["trade_permission"]=="WAIT"
    assert "queue_paper" not in Path("trader/fokus_3f.py").read_text()
