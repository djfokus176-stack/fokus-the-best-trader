"""Experimental, informational early M1 direction watches (not PAPER trades).

Only independently verified, CLOSED broker candles may be passed by the UI.
No trade creation, broker orders, backfilled fills, hit-rate estimates or
changes to AUTO's six trading strategy filters and MTF/calendar gates.
A watch is deliberately easier to trigger than a fully validated setup.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from .strategy import indicators

MIN_WATCH_BARS = 70


@dataclass(frozen=True)
class Watch:
    side: str  # LONG / SHORT / WAIT, always informational
    score: int
    countertrend: bool
    reason: str
    closed_utc: object


def evaluate_early_watch(closed: pd.DataFrame) -> Watch:
    """Lightweight early-bias heuristic on the last *closed* M1 bar only."""
    timestamp = closed.index[-1] if closed is not None and len(closed) else None
    no = lambda why: Watch("WAIT",0,False,why,timestamp)
    if (closed is None or len(closed) < MIN_WATCH_BARS
            or not isinstance(closed.index,pd.DatetimeIndex)
            or closed.index.tz is None or not closed.index.is_monotonic_increasing
            or closed.index.has_duplicates):
        return no("Brak co najmniej 70 uporządkowanych, zamkniętych M1.")
    required=("Open","High","Low","Close")
    if not all(key in closed.columns for key in required):
        return no("Brak pełnego OHLC.")
    data=closed[list(required)].tail(MIN_WATCH_BARS)
    import numpy as np
    if not np.isfinite(data.to_numpy(dtype=float)).all():
        return no("Niekompletne OHLC.")
    if ((data.High < data[["Open","Low","Close"]].max(axis=1)).any()
        or (data.Low > data[["Open","High","Close"]].min(axis=1)).any()):
        return no("Wadliwa świeca OHLC.")
    d=indicators(closed)
    cur,prev=d.iloc[-1],d.iloc[-2]
    atr=float(cur.ATR)
    rsi=float(cur.RSI)
    old_rsi=float(prev.RSI)
    if not all(math.isfinite(x) for x in (atr,rsi,old_rsi)) or atr<=0:
        return no("Brak ATR lub RSI.")
    move=float(cur.Close-prev.Close)
    bullish=(cur.Close>cur.Open and move>=.10*atr)
    bearish=(cur.Close<cur.Open and move<=-.10*atr)
    # The separate watch detects trend continuation OR a first rebound
    # before slower EMA21 catches up. Never claim executable entry.
    long_points={
        "świeca wzrostowa":bullish,
        "RSI rośnie":rsi>old_rsi+1,
        "EMA9 skręca w górę":cur.EMA9>prev.EMA9,
        "cena nad EMA9":cur.Close>cur.EMA9,
        "cena nad EMA21":cur.Close>cur.EMA21,
        "wybicie szczytu poprzedniej świecy":cur.Close>prev.High,
    }
    short_points={
        "świeca spadkowa":bearish,
        "RSI spada":rsi<old_rsi-1,
        "EMA9 skręca w dół":cur.EMA9<prev.EMA9,
        "cena pod EMA9":cur.Close<cur.EMA9,
        "cena pod EMA21":cur.Close<cur.EMA21,
        "wybicie dołka poprzedniej świecy":cur.Close<prev.Low,
    }
    ls=sum(long_points.values())
    ss=sum(short_points.values())
    if bullish and ls>=3 and ls>=ss+2:
        counter=bool(cur.EMA9<cur.EMA21)
        notes=", ".join(k for k,ok in long_points.items() if ok)
        return Watch("LONG",ls,counter,
                     ("Wstępne odbicie przeciw trendowi EMA9/21. " if counter
                      else "Momentum wzrostowe M1. ")+notes+". Bez potwierdzenia PAPER.",
                     timestamp)
    if bearish and ss>=3 and ss>=ls+2:
        counter=bool(cur.EMA9>cur.EMA21)
        notes=", ".join(k for k,ok in short_points.items() if ok)
        return Watch("SHORT",ss,counter,
                     ("Wstępny spadek przeciw trendowi EMA9/21. " if counter
                      else "Momentum spadkowe M1. ")+notes+". Bez potwierdzenia PAPER.",
                     timestamp)
    return Watch("WAIT",max(ls,ss),False,
                 f"Za mało przewagi na M1: LONG {ls}/6, SHORT {ss}/6. "
                 "Brak wskazania obserwacyjnego.",timestamp)


def recent_watch_markers(frame: pd.DataFrame, *, last_bars=45, limit=8):
    """Causally mark *changes* in early watch direction on CLOSED M1 only."""
    if frame is None or len(frame)<MIN_WATCH_BARS or last_bars<1:
        return []
    result=[]
    begin=max(MIN_WATCH_BARS-1,len(frame)-last_bars)
    # Evaluate previous candle too so first visible 'change' is grounded.
    first=max(MIN_WATCH_BARS-1,begin-1)
    previous=None
    for i in range(first,len(frame)):
        window=frame.iloc[:i+1]
        got=evaluate_early_watch(window)
        if i>=begin and got.side in ("LONG","SHORT") and got.side!=previous:
            result.append({
                "time":got.closed_utc, "side":got.side,
                "close":float(window.Close.iloc[-1]),
                "high":float(window.High.iloc[-1]),
                "low":float(window.Low.iloc[-1]),
                "countertrend":got.countertrend,
                "score":got.score, "reason":got.reason,
            })
        previous=got.side
    return result[-limit:]
