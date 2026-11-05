"""PAPER research: chronological holdout + rolling checks, with no future candles.

This is validation tooling, not trained ML and not evidence of profitable live
trading. Positions use mid-defined SL/TP and fixed BID/ASK spread model v2.
"""
from __future__ import annotations
import math
import pandas as pd
from .strategy import simulate_outcome
from .strategies_pro import decide_any, ALL_STRATEGIES

FINAL_STATUSES = {"WIN","LOSS","TIMEOUT"}

def _outcome(future, action, entry, stop, target, spread, slippage, holding):
    """Conservative fixed-horizon mark-to-market after stop/target tests."""
    status, pnl=simulate_outcome(future,action,entry,stop,target,spread,slippage)
    if status=="PENDING" and len(future)>=holding:
        open_mid=float(future.iloc[0].Open)
        close_mid=float(future.iloc[-1].Close)
        entry_ex=(open_mid+spread/2+slippage if action=="LONG"
                  else open_mid-spread/2-slippage)
        exit_ex=(close_mid-spread/2-slippage if action=="LONG"
                 else close_mid+spread/2+slippage)
        pnl=(exit_ex-entry_ex if action=="LONG" else entry_ex-exit_ex)
        return "TIMEOUT",round(pnl,2)
    return status,pnl


def replay(frame: pd.DataFrame, strategy: str, spread: float=.6,
           slippage: float=.25, holding: int=20,
           evaluation_start: int=85, evaluation_end: int|None=None) -> pd.DataFrame:
    """Only emit predictions using prefix [:i] and future candles [i:i+holding].
    Each setup waits for next candle OPEN, positions never overlap.
    """
    cols=["time_utc","strategy","side","status","pnl_pts","r_net",
          "entry_mid","sl_mid","tp_mid","spread","reason"]
    if frame is None or len(frame)<100:
        return pd.DataFrame(columns=cols)
    if strategy not in ALL_STRATEGIES or spread<0 or slippage<0 or holding<2:
        raise ValueError("Niepoprawne dane, strategia lub koszty.")
    end=min(int(evaluation_end or len(frame)),len(frame))
    start=max(85,int(evaluation_start))
    events=[]
    i=start
    while i+holding<=end:
        # Prefix contains ONLY completed bars, evaluated at i-1.
        decision=decide_any(frame.iloc[:i],strategy,spread=spread)
        if decision.action not in ("LONG","SHORT"):
            i+=1
            continue
        future=frame.iloc[i:i+holding]
        status,pnl=_outcome(future,decision.action,decision.entry,
                            decision.stop,decision.target,spread,slippage,holding)
        if status=="PENDING":  # no incomplete positions in performance stats
            i+=holding
            continue
        risk=abs(float(decision.entry)-float(decision.stop))+spread+2*slippage
        events.append(dict(time_utc=frame.index[i-1],strategy=strategy,
            side=decision.action,status=status,pnl_pts=round(float(pnl),2),
            r_net=round(float(pnl)/risk,4) if risk>0 else 0,
            entry_mid=decision.entry,sl_mid=decision.stop,tp_mid=decision.target,
            spread=spread,reason=decision.reason))
        i+=holding
    return pd.DataFrame(events,columns=cols)


def stats(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"n":0,"wins":0,"win_rate_pct":None,"expectancy_pts":None,
                "profit_factor":None,"sum_pts":0.0,"max_drawdown_pts":0.0,
                "avg_r":None,"status":"BRAK TRANSAKCJI"}
    t=trades[trades.status.isin(FINAL_STATUSES)].copy()
    if t.empty:
        return stats(pd.DataFrame())
    pnl=t.pnl_pts.astype(float)
    wins=int((t.status=="WIN").sum())
    gross_positive=float(pnl[pnl>0].sum())
    gross_negative=float(-pnl[pnl<0].sum())
    equity=pnl.cumsum()
    drawdown=equity-equity.cummax().clip(lower=0)
    n=len(t)
    return {
      "n":n,"wins":wins,"win_rate_pct":round(100*wins/n,2),
      "expectancy_pts":round(float(pnl.mean()),3),
      "profit_factor":round(gross_positive/gross_negative,3) if gross_negative>0 else None,
      "sum_pts":round(float(pnl.sum()),2),
      "max_drawdown_pts":round(abs(float(drawdown.min())),2),
      "avg_r":round(float(t.r_net.mean()),3),
      "status":"ZA MAŁA PRÓBA (<30)" if n<30 else "WYMAGA DALSZEJ WALIDACJI",
    }


def chronological_report(frame, strategies=ALL_STRATEGIES, spread=.6,
                         slippage=.25, holding=20, split=.70):
    """Predefined 70/30 split, NO parameter optimization.
    The latter 30% is a temporal holdout, not guaranteed unseen data.
    """
    if not 0.5<=split<=0.85:
        raise ValueError("Podział próby poza zakresem 0.5-0.85")
    n=len(frame)
    boundary=int(n*split)
    result=[]
    for strategy in strategies:
        inside=replay(frame,strategy,spread,slippage,holding,85,boundary)
        outside=replay(frame,strategy,spread,slippage,holding,max(85,boundary),n)
        for label, trades in (("TRAIN / REPLAY",inside),("HOLDOUT / PÓŹNIEJSZE",outside)):
            record={"strategia":strategy,"okres":label,**stats(trades)}
            result.append(record)
    return pd.DataFrame(result)


def rolling_oos(frame, strategy, spread=.6, slippage=.25,
                warmup=120, fold_size=80, holding=20):
    """Chronologically non-overlapping folds with fixed rules (not self-learning).
    Earlier bars provide indicators; future bars never shape entry signals.
    """
    windows=[]
    start=max(warmup,85)
    while start+holding<len(frame):
        end=min(len(frame),start+fold_size)
        t=replay(frame,strategy,spread,slippage,holding,start,end)
        windows.append({"start":str(frame.index[start]),"end":str(frame.index[end-1]),
                        "trades":len(t),**stats(t)})
        start=end
    return pd.DataFrame(windows)
