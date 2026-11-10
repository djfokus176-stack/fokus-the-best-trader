"""New ideas are strictly closed-bar SHADOW hypotheses, never AUTO orders."""
import numpy as np
import pandas as pd
import pytest
from trader import research_setups as rs
from trader.structure_levels import structural_room
from trader.strategies_pro import ALL_STRATEGIES,decide_any
from trader.research import replay
from trader.research_comparison import RESEARCH_CASES


def sample(n=150):
    idx=pd.date_range("2026-11-09T10:00:00Z",periods=n,freq="min")
    price=100+np.arange(n)*.01
    return pd.DataFrame(dict(Open=price,Close=price+.02,
                             High=price+.3,Low=price-.3,
                             Spread=np.full(n,.6)),index=idx)


def open_day(day="2026-11-10", missing=None):
    # Time is a M1 UTC CLOSE label; NYSE cash open is at 09:30 ET.
    idx=pd.date_range(day+" 08:00",day+" 10:00",freq="min",
                      tz="America/New_York").tz_convert("UTC")
    df=pd.DataFrame(dict(Open=np.full(len(idx),100.),
                         High=np.full(len(idx),100.1),
                         Low=np.full(len(idx),99.9),
                         Close=np.full(len(idx),100.),
                         Spread=np.full(len(idx),.25)),index=idx)
    if missing is not None:
        df=df.drop(pd.Timestamp(day+" "+missing,
                                tz="America/New_York").tz_convert("UTC"))
    return df


def test_new_patterns_are_not_six_auto_strategies():
    assert len(ALL_STRATEGIES)==6
    assert rs.NY_OPEN_TRAP not in ALL_STRATEGIES
    assert rs.EMA_PULLBACK_RETEST not in ALL_STRATEGIES
    assert len(RESEARCH_CASES)==12
    assert set(rs.RESEARCH_STRATEGIES).issubset(
        {name for _,name,_ in RESEARCH_CASES})


def test_structural_pivot_excludes_current_and_future_bar():
    data=sample()
    # Clear old confirmed HIGH (two closed bars on either side).
    data.loc[data.index[70],"High"]=105
    initial=structural_room(data,"LONG",entry=103,risk=2,min_rr=1.35)
    assert initial.blocked and initial.level==105
    newer=data.copy()
    newer.loc[newer.index[-1],"High"]=200
    assert structural_room(newer,"LONG",103,2,1.35)==initial
    # Confirmed pivot disappears without the two subsequent completed bars.
    near=data.iloc[:72].copy()
    assert structural_room(near,"LONG",103,2,1.35).level is None


def test_structural_mode_is_explicit_optin_and_default_remains_identical():
    frame=sample()
    for name in ("EMA TREND","DRUGA FALA","EMA PULLBACK"):
        original=decide_any(frame,name,spread=.6)
        explicit=decide_any(frame,name,spread=.6,obstacle_mode="legacy")
        assert original==explicit
    with pytest.raises(ValueError):
        decide_any(frame,"EMA TREND",obstacle_mode="made_up")


def test_ny_trap_requires_entire_15_minute_opening_window():
    missing=open_day(missing="09:37")
    a,p=rs.evaluate_research(missing.loc[
        :pd.Timestamp("2026-11-10 09:47",tz="America/New_York").tz_convert("UTC")],
        rs.NY_OPEN_TRAP,spread=.25)
    assert a.action=="WAIT"
    assert p["stage"]==0
    assert "Niepełny" in a.reason


def test_ny_trap_confirms_breakout_only_after_closed_candle():
    df=open_day()
    # At 09:46 the prior completed candle shows a breakout above the range.
    b=pd.Timestamp("2026-11-10 09:46",tz="America/New_York").tz_convert("UTC")
    df.loc[b,["Open","High","Low","Close"]]=[100.8,102.,100.7,101.7]
    partly=df.loc[:b]
    d,p=rs.evaluate_research(partly,rs.NY_OPEN_TRAP,spread=.25)
    assert d.action=="WAIT"
    # The next completed bar has not yet confirmed re-entry.
    a=pd.Timestamp("2026-11-10 09:47",tz="America/New_York").tz_convert("UTC")
    df.loc[a,["Open","High","Low","Close"]]=[101.6,101.7,100.5,100.8]
    d,p=rs.evaluate_research(df.loc[:a],rs.NY_OPEN_TRAP,spread=.25)
    assert p["stage"]>=2 and p["side"]=="SHORT"
    assert d.action in ("WAIT","SHORT")
    # No later market data is allowed to alter this decision.
    df.loc[df.index[-1],"High"]=900
    d2,p2=rs.evaluate_research(df.loc[:a],rs.NY_OPEN_TRAP,spread=.25)
    assert (d,p)==(d2,p2)


def test_ny_market_dst_shifts_utc_open():
    for d,expected in (("2026-01-12","14:31"),("2026-07-13","13:31")):
        open_utc=pd.Timestamp(d+" 09:31",tz="America/New_York").tz_convert("UTC")
        assert open_utc.strftime("%H:%M")==expected


def test_research_candidate_never_approved_by_auto_mtf_or_shown_as_order():
    frame=sample()
    for name in rs.RESEARCH_STRATEGIES:
        d,meta=rs.evaluate_research(frame,name)
        assert meta["research_only"]
        assert 0<=meta["stage"]<=3
        assert d.strategy==name
        assert len(meta["checks"])==3


def test_replay_allows_research_only_with_no_live_changes():
    frame=sample()
    for name in rs.RESEARCH_STRATEGIES:
        result=replay(frame,name,spread=.6,evaluation_start=105,
                      holding=4,max_history=130)
        assert "status" in result.columns


def test_comparison_has_fixed_cases_without_reoptimizing_auto():
    assert RESEARCH_CASES[0][1]==ALL_STRATEGIES[0]
    assert {mode for _,_,mode in RESEARCH_CASES}=={
        "legacy","confirmed_swings"}
