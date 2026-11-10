"""Fixed, predeclared offline comparison of new research setups and old guards.

No hyperparameter search. Time split is chronological after indicator warmup.
Comparative leaderboard is RESEARCH only: not deployed strategy selection.
"""
from __future__ import annotations

from math import sqrt
import pandas as pd

from .strategies_pro import ALL_STRATEGIES
from .ema50_wave import STRATEGY_NAME as WAVE_NAME
from .range_rejection import NAME as RANGE_NAME
from .research_setups import NY_OPEN_TRAP, EMA_PULLBACK_RETEST
from .research import replay,stats
from .mtf_replay import (validate_close_time_m1,build_higher_closed_bars,
                         HistoricalMTFGate)

RESEARCH_CASES=(
    *((name,name,"legacy") for name in ALL_STRATEGIES),
    ("EMA TREND | SWING","EMA TREND","confirmed_swings"),
    ("EMA PULLBACK | SWING","EMA PULLBACK","confirmed_swings"),
    (NY_OPEN_TRAP,NY_OPEN_TRAP,"legacy"),
    (EMA_PULLBACK_RETEST,EMA_PULLBACK_RETEST,"confirmed_swings"),
    (WAVE_NAME,WAVE_NAME,"legacy"),
    (RANGE_NAME,RANGE_NAME,"legacy"),
)


def compare_research_methods(m1:pd.DataFrame, *, spread:float=.6,
                             slippage:float=.25, holding:int=20,
                             split:float=.7, spread_mode:str="fixed",
                             mtf:bool=False, max_candles:int=6500):
    """Compare predeclared strategies with no overlap per strategy and period.

    MTF=True shares the production vote consensus (2 of 3, no opposing
    higher trend) only AFTER 70 complete derived H1 hours. Without MTF
    the candidate comparison is an exploratory *pre-gate* experiment.
    It does NOT reproduce all remote worker gates, funding or broker fills.
    """
    validate_close_time_m1(m1)
    if not 500<=len(m1)<=max_candles or not 0.5<=split<=.85:
        raise ValueError("Badanie wymaga 500–6500 świec UTC M1 i podziału 50–85%.")
    if spread_mode not in ("fixed","historical") or spread<0 or slippage<0 or holding<2:
        raise ValueError("Nieprawidłowe koszty lub konfiguracja badania.")
    gate=None
    warmup=120
    counts={}
    if mtf:
        higher=build_higher_closed_bars(m1)
        counts={k:len(v) for k,v in higher.items()}
        if len(higher["HOUR"])<70:
            raise ValueError("Dla MTF potrzebujemy min. 70 kompletnych H1.")
        gate=HistoricalMTFGate(m1,higher)
        warmup=max(warmup,int(m1.index.searchsorted(higher["HOUR"].index[69],side="right")))
    if len(m1)-warmup<2*holding+80:
        raise ValueError("Za krótka ocena po rozgrzewce, potrzebne kolejne dni.")
    boundary=warmup+int((len(m1)-warmup)*split)
    records=[]
    logs=[]
    for label,strategy,obstacles in RESEARCH_CASES:
        for phase,start,end in (("WCZESNIEJSZE 70%",warmup,boundary),
                                ("POZNIEJSZE 30%",boundary,len(m1))):
            veto={"candidates":0,"rejected":0}
            def _gate(decision,t):
                veto["candidates"]+=1
                allowed=gate.allow(decision,t)
                if not allowed:veto["rejected"]+=1
                return allowed
            trades=replay(m1,strategy,spread=spread,slippage=slippage,
                          holding=holding,evaluation_start=start,
                          evaluation_end=end,trade_gate=_gate if mtf else None,
                          max_history=160,spread_mode=spread_mode,
                          obstacle_mode=obstacles)
            scored=trades[trades.status.isin(["WIN","LOSS","TIMEOUT"])] if not trades.empty else trades
            metrics=stats(trades)
            n=int(metrics["n"])
            pnl=scored.pnl_pts.astype(float).tolist() if n else []
            mean=sum(pnl)/n if n else None
            if n>1:
                variance=sum((x-mean)**2 for x in pnl)/(n-1)
                lower95=mean-1.96*sqrt(variance/n)
            else:
                lower95=None
            eligible=(phase=="POZNIEJSZE 30%" and n>=30 and
                      lower95 is not None and lower95>0)
            records.append({
                "metoda":label,"strategia":strategy,"ochrona_poziomow":obstacles,
                "okres":phase,"mtf":bool(mtf),"spread_mode":spread_mode,
                "kandydaci_mtf":veto["candidates"] if mtf else None,
                "odrzucone_mtf":veto["rejected"] if mtf else None,
                "lower95_avg_pnl":round(lower95,3) if lower95 is not None else None,
                "kwalifikuje_ranking":eligible,**metrics})
            if not trades.empty:
                history=trades.copy()
                history["metoda"]=label
                history["okres"]=phase
                history["mtf"]=bool(mtf)
                logs.append(history)
    result=pd.DataFrame(records)
    later=result[result.okres=="POZNIEJSZE 30%"].copy()
    qualified=later[later.kwalifikuje_ranking].sort_values(
        "lower95_avg_pnl",ascending=False)
    ranks={name:i for i,name in enumerate(qualified.metoda.tolist(),1)}
    result["ranking_kwalifikowany"]=result.apply(
        lambda r:ranks.get(r["metoda"]) if r["okres"]=="POZNIEJSZE 30%" else None,
        axis=1)
    report=(pd.concat(logs,ignore_index=True) if logs else
            pd.DataFrame(columns=["time_utc","strategy","side","status","pnl_pts",
                                  "metoda","okres","mtf"]))
    return result,report,{"h1_warmup_bars":warmup,"training_cutoff":str(m1.index[boundary]),
                          "higher_counts":counts,
                          "leader":qualified.iloc[0].metoda if not qualified.empty else None,
                          "minimum_holdout_closed":30,
                          "note":"Próg >=30 to minimum diagnostyczne, nie dowód przewagi."}
