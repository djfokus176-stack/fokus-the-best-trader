"""EMA50 WAVE — independent, closed-bar PAPER comparison hypothesis.

Based on the user's separate legacy program's *signal rules*, without
importing/changing that program or its historical archive. This implementation
evaluates ONLY the latest finished bar and has NO backfilled trades.

This is an optional candidate strategy, NOT a copy of legacy performance,
real money brokerage automation, or evidence of positive expectancy.
"""
from __future__ import annotations
import math
import pandas as pd
import numpy as np
from .strategy import Decision

STRATEGY_NAME="EMA50 WAVE (PORÓWNANIE)"


def wave_decision(frame: pd.DataFrame, spread: float=.6,
                  min_rr: float=1.35) -> Decision:
    """Legacy-inspired EMA/pattern + RSI signal, no next-bar knowledge.

    A signal on last closed bar can queue PENDING, then the shared PAPER
    engine reconstructs OPEN from the following *closed* candle.
    """
    def wait(reason,atr=None,bias="NEUTRAL"):
        return Decision("WAIT",STRATEGY_NAME,reason,atr=atr,bias=bias)
    if frame is None or len(frame)<85:
        return wait("Za mało zamkniętych świec do rozgrzewki EMA/RSI/ATR.")
    if not math.isfinite(spread) or spread<0:
        return wait("Niepoprawny spread.")
    cols=("Open","High","Low","Close")
    if any(c not in frame.columns for c in cols):
        return wait("Brak wymaganych kolumn OHLC.")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        return wait("Niespójne etykiety czasowe OHLC.")
    if not np.isfinite(frame[list(cols)].tail(85).to_numpy(dtype=float)).all():
        return wait("Wadliwe OHLC.")
    df=frame.copy()
    for n in (9,21,50):
        df[f"EMA{n}"]=df.Close.ewm(span=n,adjust=False).mean()
    delta=df.Close.diff()
    up=delta.where(delta>0,0).rolling(14,min_periods=14).mean()
    down=(-delta.where(delta<0,0)).rolling(14,min_periods=14).mean()
    rs=up/down.replace(0,np.nan)
    df["RSI"]=(100-(100/(1+rs))).fillna(50)
    previous=df.Close.shift()
    tr=pd.concat([(df.High-df.Low).abs(),(df.High-previous).abs(),
                  (df.Low-previous).abs()],axis=1).max(axis=1)
    df["ATR"]=tr.rolling(14,min_periods=14).mean()
    a,b=df.iloc[-1],df.iloc[-2]
    atr=float(a.ATR)
    if not math.isfinite(atr) or atr<=0:
        return wait("ATR niegotowy.")
    bias=("UP" if a.EMA9>a.EMA21>a.EMA50 else
          "DOWN" if a.EMA9<a.EMA21<a.EMA50 else "NEUTRAL")
    if spread>max(1.2,.4*atr):
        return wait("Spread przekracza dopuszczalny koszt do ATR.",atr,bias)
    o,h,l,c=(float(a[n]) for n in ("Open","High","Low","Close"))
    po,pc=float(b.Open),float(b.Close)
    body=abs(c-o);rng=max(.01,h-l)
    upper=h-max(o,c);lower=min(o,c)-l
    close_high=(c-l)/rng>=.55
    close_low=(h-c)/rng>=.55
    ema9,ema21,ema50=float(a.EMA9),float(a.EMA21),float(a.EMA50)
    ema9_slope=ema9-float(df.EMA9.iloc[-4])
    ema21_slope=ema21-float(df.EMA21.iloc[-4])
    # The legacy 'Tylko Pewniaki' consolidation filter. Do not substitute
    # an unknown historical learning state or a relaxed 'Wysoka' sensitivity.
    if (abs(ema9-ema21)<.15*atr and abs(ema9_slope)<.20*atr):
        return wait("Filtr konsolidacji EMA (odpowiednik starego).",atr,bias)
    bullish=[
        ("pin bar",lower>=body*1.7 and lower>=rng*.40 and close_high and c>o),
        ("engulfing",pc<po and c>o and c>po and body>=atr*.35),
        ("pullback EMA21",l<=ema21 and c>ema9 and c>o and close_high),
        ("cross wave EMA",c>o and c>ema9 and ema9>ema21 and
         float(df.EMA9.iloc[-3])<=float(df.EMA21.iloc[-3])),
    ]
    bearish=[
        ("pin bar",upper>=body*1.7 and upper>=rng*.40 and close_low and c<o),
        ("engulfing",pc>po and c<o and c<po and body>=atr*.35),
        ("pullback EMA21",h>=ema21 and c<ema9 and c<o and close_low),
        ("cross wave EMA",c<o and c<ema9 and ema9<ema21 and
         float(df.EMA9.iloc[-3])>=float(df.EMA21.iloc[-3])),
    ]
    long_pattern=next((n for n,matched in bullish if matched),None)
    short_pattern=next((n for n,matched in bearish if matched),None)
    trend_up=(ema9>ema21 and c>ema50 and ema9_slope>0
              and ema21_slope>=0)
    trend_down=(ema9<ema21 and c<ema50 and ema9_slope<0
                and ema21_slope<=0)
    rsi=float(a.RSI)
    if long_pattern and trend_up and 42<=rsi<=72:
        side="LONG";pattern=long_pattern
        swing=float(df.Low.iloc[-6:].min())
        sl_dist=min(14.,max(8.,c-swing+atr,atr*3.5))
        stop=c-sl_dist;target=c+30.
    elif short_pattern and trend_down and 28<=rsi<=58:
        side="SHORT";pattern=short_pattern
        swing=float(df.High.iloc[-6:].max())
        sl_dist=min(14.,max(8.,swing-c+atr,atr*3.5))
        stop=c+sl_dist;target=c-30.
    else:
        return wait("Brak zakończonej formacji EMA50/RSI i trendu.",atr,bias)
    # Entry is only a proposed MID anchor, NOT known next-bar fill.
    risk=abs(stop-c)
    rr=(30.-spread)/(risk+spread) if risk>0 else 0.
    if risk<=spread*1.5 or rr<min_rr:
        return wait("Koszty / RR nie uzasadniają nowej symulacji.",atr,bias)
    return Decision(side,STRATEGY_NAME,
        f"Zamknięta świeca: {pattern}; EMA9/21/50, RSI={rsi:.1f}, "
        f"ATR={atr:.2f}. Bez przyszłego OPEN. Wymagane MTF/makro/clock przed PAPER.",
        round(c,2),round(stop,2),round(target,2),round(rr,2),
        round(atr,2),bias)
