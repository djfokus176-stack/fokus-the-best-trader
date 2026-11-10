"""No external API calls. Assert honest independent 3-stage + SHADOW research."""
import pandas as pd
from trader.strategy import Decision
from trader.strategy_progress import progress_for_votes
from trader import shadow_learning
from trader.strategy_selector import select_approved


def frame(n=120):
    t=pd.date_range("2026-11-10T08:00Z",periods=n,freq="min")
    close=[100+.01*i for i in range(n)]
    return pd.DataFrame({"Open":close,"High":[x+.2 for x in close],
                         "Low":[x-.2 for x in close],"Close":close},index=t)


def test_stages_show_strategy_and_only_allow_3_of_3_with_global_approval():
    f=frame()
    rows=[{"Strategia":"EMA TREND","Setup OHLC":"LONG",
           "Po filtrze MTF":"LONG","Powód":"OK"},
          {"Strategia":"LIQUIDITY SWEEP","Setup OHLC":"WAIT",
           "Po filtrze MTF":"WAIT","Powód":"brak poziomu"}]
    stages=progress_for_votes(f,rows,blockers=[])
    assert stages[0]["strategy"]=="EMA TREND"
    assert stages[0]["progress"]=="3/3"
    assert stages[0]["side"]=="LONG"
    assert len(stages[0]["criteria"])==3
    assert stages[1]["progress"] in ("0/3","1/3","2/3")
    blocked=progress_for_votes(f,rows,blockers=["MACRO_BLACKOUT"])
    assert blocked[0]["progress"]=="2/3"
    rows[0]["Po filtrze MTF"]="WAIT"
    assert progress_for_votes(f,rows)[0]["progress"]=="2/3"


def test_shadow_uses_next_consecutive_closed_bar_and_fees(monkeypatch):
    f=frame()
    # Flat fixed entry for test: selected by independent strategy, NOT AUTO.
    monkeypatch.setattr(shadow_learning,"decide_any",
        lambda *args,**kwargs:Decision("LONG","EMA TREND","test",100,99,101,1.5))
    votes=[{"Strategia":"EMA TREND","Setup OHLC":"LONG",
            "Po filtrze MTF":"LONG"}]
    base=shadow_learning.advance_shadow({},f,votes,[],spread=.20)
    assert base["active"]["EMA TREND"]["status"]=="PENDING"
    # No false fill or duplicate trial for repeated same candle.
    same=shadow_learning.advance_shadow(base,f,votes,[],spread=.20)
    assert same["closed"]["EMA TREND"]==[]
    next_t=f.index[-1]+pd.Timedelta(minutes=1)
    new=pd.DataFrame([{"Open":100.0,"High":101.2,"Low":99.8,"Close":100.8}],index=[next_t])
    afterward=shadow_learning.advance_shadow(same,pd.concat([f,new]),[],[],spread=.2)
    assert len(afterward["closed"]["EMA TREND"])==1
    record=afterward["closed"]["EMA TREND"][0]
    assert record["status"]=="CLOSED_TP"
    assert record["pnl_pts"]==.3  # +1 MID minus .2 spread minus .5 slippage
    assert record["r"]==.3
    assert shadow_learning.shadow_scorecard(afterward)["leader"] is None


def test_shadow_gap_invalidates_instead_of_backfilling(monkeypatch):
    f=frame()
    monkeypatch.setattr(shadow_learning,"decide_any",
        lambda *args,**kwargs:Decision("SHORT","EMA TREND","test",100,101,99,1.5))
    votes=[{"Strategia":"EMA TREND","Setup OHLC":"SHORT",
            "Po filtrze MTF":"SHORT"}]
    state=shadow_learning.advance_shadow({},f,votes,[],spread=.2)
    t=f.index[-1]+pd.Timedelta(minutes=2)
    new=pd.DataFrame([{"Open":100,"High":100.2,"Low":98.8,"Close":99}],index=[t])
    result=shadow_learning.advance_shadow(state,pd.concat([f,new]),[],[],spread=.2)
    assert result["gaps"]==1
    assert result["invalidated"]["EMA TREND"]==1
    assert result["closed"]["EMA TREND"]==[]
    assert "EMA TREND" not in result["active"]


def test_selector_uses_learning_only_when_all_approved_have_evidence(monkeypatch):
    from trader import strategy_selector as s
    monkeypatch.setattr(s,"market_context",lambda df:("TREND WZROSTOWY","BRAK","READY"))
    candidates=[Decision("LONG","EMA TREND","base",100,99,102,1.7),
                Decision("LONG","LIQUIDITY SWEEP","base",100,99,102,1.6)]
    chosen,_=select_approved(None,candidates)
    assert chosen.strategy=="EMA TREND"
    one={"strategies":[{"strategy":"LIQUIDITY SWEEP","eligible":True,
                        "lower95_r_holdout":.4}]}
    chosen,_=select_approved(None,candidates,learning=one)
    assert chosen.strategy=="EMA TREND"  # No cherry-picking one known winner
    both={"strategies":[{"strategy":"LIQUIDITY SWEEP","eligible":True,
                         "lower95_r_holdout":.4},
                        {"strategy":"EMA TREND","eligible":True,
                         "lower95_r_holdout":.1}]}
    chosen,explained=select_approved(None,candidates,learning=both)
    assert chosen.strategy=="LIQUIDITY SWEEP"
    assert "FORWARD SHADOW" in explained.selection_reason
    assert "SHADOW lower95 R" in explained.ranking[0]


def test_scorecard_requires_100_independently_closed_outcomes():
    records=lambda n:[{"r":.4,"pnl_pts":.4,"utc":str(i)} for i in range(n)]
    one={"schema":1,"closed":{"EMA TREND":records(99)}}
    assert shadow_learning.shadow_scorecard(one)["leader"] is None
    one["closed"]["EMA TREND"]=records(100)
    report=shadow_learning.shadow_scorecard(one)
    assert report["leader"]=="EMA TREND"
    assert report["strategies"][1]["closed"]==100
    assert report["strategies"][1]["holdout"]==30


def test_extra_range_rejection_is_research_only_and_not_auto():
    from trader.strategies_pro import ALL_STRATEGIES, decide_any
    from trader.range_rejection import NAME, RESEARCH_ONLY
    assert RESEARCH_ONLY is True
    assert NAME not in ALL_STRATEGIES
    assert len(ALL_STRATEGIES)==6
    too_short=frame(90)
    decision=decide_any(too_short,NAME,spread=.5)
    assert decision.strategy==NAME
    assert decision.action=="WAIT"
