"""PAPER research: chronological holdout + rolling checks, with no future candles.

This is validation tooling, not trained ML and not evidence of profitable live
trading. Positions use mid-defined SL/TP; historical costs are optional.
Missing M1 bars during hypothetical positions invalidate their outcomes.
"""
from __future__ import annotations
import math
import pandas as pd
from .strategy import simulate_outcome
from .strategies_pro import decide_any, ALL_STRATEGIES

FINAL_STATUSES = {"WIN","LOSS","TIMEOUT"}

def _outcome(future, action, entry, stop, target, spread, slippage, holding,
             *, exit_spreads=None, timeout_exit_spread=None):
    """Historical spread: signal-close entry and last-known intrabar exit costs."""
    status, pnl=simulate_outcome(future,action,entry,stop,target,spread,slippage,
                                 exit_spreads=exit_spreads)
    if status=="PENDING" and len(future)>=holding:
        open_mid=float(future.iloc[0].Open)
        close_mid=float(future.iloc[-1].Close)
        entry_ex=(open_mid+spread/2+slippage if action=="LONG"
                  else open_mid-spread/2-slippage)
        final_spread=spread if timeout_exit_spread is None else float(timeout_exit_spread)
        exit_ex=(close_mid-final_spread/2-slippage if action=="LONG"
                 else close_mid+final_spread/2+slippage)
        pnl=(exit_ex-entry_ex if action=="LONG" else entry_ex-exit_ex)
        return "TIMEOUT",round(pnl,2)
    return status,pnl


def _consecutive_future(future: pd.DataFrame, signal_close) -> tuple[pd.DataFrame,bool]:
    """Do not price unseen M1 bars. Return verified prefix and gap flag."""
    expected=pd.Timestamp(signal_close)+pd.Timedelta(minutes=1)
    for n,stamp in enumerate(future.index):
        if stamp!=expected:
            return future.iloc[:n],True
        expected+=pd.Timedelta(minutes=1)
    return future,False


def _bars_through_exit(future: pd.DataFrame, side: str, stop: float, target: float) -> int:
    """How many consecutive future CLOSED candles were really occupied?

    Uses exactly the same MID high/low SL-first priority as simulate_outcome.
    The decision at the following candle will see the closed exit candle,
    but nothing beyond it. A gap invalidating entry occupies just one bar.
    """
    if future.empty:
        return 0
    for offset, bar in enumerate(future.itertuples(index=False),start=1):
        if side=="LONG" and (float(bar.Low)<=stop or float(bar.High)>=target):
            return offset
        if side=="SHORT" and (float(bar.High)>=stop or float(bar.Low)<=target):
            return offset
    return len(future)


def replay(frame: pd.DataFrame, strategy: str, spread: float=.6,
           slippage: float=.25, holding: int=20,
           evaluation_start: int=85, evaluation_end: int|None=None,
           trade_gate=None, max_history: int|None=None,
           spread_mode: str="fixed") -> pd.DataFrame:
    """Only emit predictions using prefix [:i] and future candles [i:i+holding].
    Each setup waits for next candle OPEN, positions never overlap.
    """
    cols=["time_utc","strategy","side","status","pnl_pts","r_net",
          "entry_mid","sl_mid","tp_mid","spread","entry_spread",
          "exit_spread","spread_mode","reason"]
    if frame is None or len(frame)<100:
        return pd.DataFrame(columns=cols)
    if strategy not in ALL_STRATEGIES or spread<0 or slippage<0 or holding<2:
        raise ValueError("Niepoprawne dane, strategia lub koszty.")
    if spread_mode not in ("fixed","historical"):
        raise ValueError("Nieznany model spreadu.")
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None or (
        not frame.index.is_monotonic_increasing or frame.index.has_duplicates):
        raise ValueError("Replay wymaga uporządkowanych, unikalnych M1 ze strefą UTC.")
    if spread_mode=="historical":
        if "Spread" not in frame.columns:
            raise ValueError("Tryb historyczny wymaga kolumny Spread.")
        spreads=pd.to_numeric(frame.Spread,errors="coerce")
        if spreads.isna().any() or not spreads.map(math.isfinite).all() or (spreads<0).any():
            raise ValueError("Nieprawidłowe historyczne spready.")
    end=min(int(evaluation_end or len(frame)),len(frame))
    start=max(85,int(evaluation_start))
    events=[]
    i=start
    while i+holding<=end:
        # Prefix contains ONLY completed bars, evaluated at i-1.
        # Fixed rolling warmup bounds CPU/memory on long CSV datasets.
        # Every result uses only candles fully closed before the signal.
        prefix=frame.iloc[max(0,i-max_history):i] if max_history else frame.iloc[:i]
        entry_spread=(float(frame.Spread.iloc[i-1]) if spread_mode=="historical"
                      else float(spread))
        decision=decide_any(prefix,strategy,spread=entry_spread)
        if decision.action not in ("LONG","SHORT"):
            i+=1
            continue
        if trade_gate is not None and not trade_gate(decision,frame.index[i-1]):
            i+=1
            continue
        future,gap=_consecutive_future(frame.iloc[i:i+holding],frame.index[i-1])
        if future.empty:
            status,pnl="INVALIDATED_GAP",None
        else:
            # M1 Spread is measured at candle CLOSE, so the following OPEN
            # can only use the PREVIOUS confirmed candle's observation.
            exit_spreads=(list(frame.Spread.iloc[i-1:i+len(future)-1].astype(float))
                          if spread_mode=="historical" else None)
            timeout_exit_spread=(float(future.Spread.iloc[-1])
                                 if spread_mode=="historical" else None)
            status,pnl=_outcome(future,decision.action,decision.entry,
                                decision.stop,decision.target,entry_spread,
                                slippage,holding,exit_spreads=exit_spreads,
                                timeout_exit_spread=timeout_exit_spread)
            if gap and status=="PENDING":
                status,pnl="INVALIDATED_GAP",None
        if status=="PENDING":  # no incomplete positions in performance stats
            i+=holding
            continue
        if status=="SKIPPED_GAP":
            # No position ever opened; the next closed bar may create a
            # different independent setup. Previously skipped full horizon.
            i+=1
            continue
        exit_bars=(_bars_through_exit(future,decision.action,
                                     float(decision.stop),float(decision.target))
                   if status in ("WIN","LOSS") else None)
        consumed=(exit_bars if exit_bars is not None else
                  max(1,len(future)+1) if status=="INVALIDATED_GAP" else holding)
        if status not in FINAL_STATUSES:
            exit_spread=None
        elif spread_mode=="fixed":
            exit_spread=entry_spread
        elif exit_bars is not None:
            # The last closed bar BEFORE the SL/TP-touching candle.
            exit_spread=float(frame.Spread.iloc[i+exit_bars-2])
        else:
            # TIMEOUT at the end of a fully observed close bar.
            exit_spread=float(future.Spread.iloc[-1])
        risk=abs(float(decision.entry)-float(decision.stop))+entry_spread+2*slippage
        events.append(dict(time_utc=frame.index[i-1],strategy=strategy,
            side=decision.action,status=status,
            pnl_pts=round(float(pnl),2) if pnl is not None else None,
            r_net=(round(float(pnl)/risk,4) if risk>0 and pnl is not None else None),
            entry_mid=decision.entry,sl_mid=decision.stop,tp_mid=decision.target,
            spread=entry_spread,entry_spread=entry_spread,
            exit_spread=exit_spread,spread_mode=spread_mode,reason=decision.reason))
        # A gap is audited but NEVER scored as a profitable or losing trade.
        # One active position at a time, but release the slot ON the first
        # actual SL/TP candle, not automatically after all 20 future bars.
        i+=max(1,consumed)
    return pd.DataFrame(events,columns=cols)


def stats(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"n":0,"wins":0,"win_rate_pct":None,
                "profitable_trades":0,"pnl_win_rate_pct":None,
                "positive_timeouts":0,"timeouts":0,
                "expectancy_pts":None,"profit_factor":None,"sum_pts":0.0,
                "max_drawdown_pts":0.0,"avg_r":None,"status":"BRAK TRANSAKCJI"}
    t=trades[trades.status.isin(FINAL_STATUSES)].copy()
    if t.empty:
        return stats(pd.DataFrame())
    pnl=t.pnl_pts.astype(float)
    # "wins" is retained for backwards compatibility and means TP HIT.
    # A TIMEOUT can close at positive P&L without ever touching target.
    wins=int((t.status=="WIN").sum())
    profit_wins=int((pnl>0).sum())
    timeouts=int((t.status=="TIMEOUT").sum())
    positive_timeouts=int(((t.status=="TIMEOUT")&(pnl>0)).sum())
    gross_positive=float(pnl[pnl>0].sum())
    gross_negative=float(-pnl[pnl<0].sum())
    equity=pnl.cumsum()
    drawdown=equity-equity.cummax().clip(lower=0)
    n=len(t)
    return {
      "n":n,"wins":wins,"win_rate_pct":round(100*wins/n,2),
      "profitable_trades":profit_wins,
      "pnl_win_rate_pct":round(100*profit_wins/n,2),
      "timeouts":timeouts,"positive_timeouts":positive_timeouts,
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
