"""Additional CLOSED-M1 research hypotheses, not connected to live AUTO/PAPER.

No lookahead: never reads bars after the signal. US opening range is the first
15 *completed* M1 candles after 09:30 America/New_York (09:31..09:45 CLOSE).
NYSE hours are a session convention for US500 CFDs; this module does not
claim to verify exchange holidays, fills, liquidity, or live orderbook data.
"""
from __future__ import annotations

from datetime import time
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd

from .market_dna import confirmed_pivots
from .strategy import Decision, indicators

NY_OPEN_TRAP = "NY OPEN TRAP (BADANIE)"
EMA_PULLBACK_RETEST = "EMA PULLBACK + RETEST (BADANIE)"
RESEARCH_STRATEGIES = (NY_OPEN_TRAP, EMA_PULLBACK_RETEST)
NY = ZoneInfo("America/New_York")


def _assessment(name, side="BRAK", checks=(False, False, False), reason=""):
    return {"strategy":name, "side":side, "stage":sum(bool(v) for v in checks),
            "checks":tuple(bool(v) for v in checks),
            "reason":reason, "research_only":True}


def _wait(name, why, side="BRAK", checks=(False, False, False), atr=None):
    return Decision("WAIT",name,why,atr=atr),_assessment(name,side,checks,why)


def _ready(frame, spread):
    return (frame is not None and len(frame)>=100 and
            isinstance(frame.index,pd.DatetimeIndex) and frame.index.tz is not None
            and frame.index.is_monotonic_increasing and not frame.index.has_duplicates
            and isfinite(float(spread)) and 0<=float(spread))


def _finish(name, side, reason, entry, stop, target, spread, min_rr, atr, checks):
    risk=entry-stop if side=="LONG" else stop-entry
    reward=target-entry if side=="LONG" else entry-target
    if not (risk>0 and reward>0 and all(isfinite(v)
            for v in (risk,reward,entry,stop,target,spread))):
        return _wait(name,"Niepoprawna geometria SL/TP.",side,checks,atr)
    rr=(reward-spread)/(risk+spread)
    if risk<=spread*1.5 or rr<min_rr:
        return _wait(name,"Zbyt duży spread lub mały RR po kosztach.",side,checks,atr)
    return (Decision(side,name,reason,round(entry,2),round(stop,2),
                     round(target,2),round(rr,2),round(atr,2),side),
            _assessment(name,side,checks,reason))


def _ny_open_trap(frame, spread, min_rr):
    name=NY_OPEN_TRAP
    if not _ready(frame,spread):
        return _wait(name,"Wymagane >=100 poprawnych, zamkniętych świec M1 UTC.")
    t=frame.index[-1].tz_convert(NY)
    btime=frame.index[-2].tz_convert(NY)
    if (t.weekday()>4 or t.date()!=btime.date() or not
            (time(9,47)<=t.time()<=time(11,0)) or
            (t-btime).total_seconds()!=60):
        return _wait(name,"Obserwacja tylko 09:47–11:00 ET po kompletnym otwarciu NYSE.")
    today=frame.loc[frame.index.tz_convert(NY).date==t.date()]
    local_close=today.index.tz_convert(NY)
    opening=today.loc[(local_close.time>=time(9,31))&
                      (local_close.time<=time(9,45))]
    required=pd.date_range(pd.Timestamp.combine(t.date(),time(9,31)).tz_localize(NY),
                           periods=15,freq="min")
    if len(opening)!=15 or not opening.index.tz_convert(NY).equals(required):
        return _wait(name,"Niepełny 15-minutowy zakres otwarcia (15 zamknięć M1).")
    d=indicators(frame)
    a,b=d.iloc[-1],d.iloc[-2]
    atr=float(a.ATR)
    if not isfinite(atr) or atr<=0:
        return _wait(name,"ATR niegotowy.")
    high,low=float(opening.High.max()),float(opening.Low.min())
    if high-low<max(1.2,2.0*spread):
        return _wait(name,"Zakres otwarcia za ciasny względem kosztów.",
                     checks=(True,False,False),atr=atr)
    # Previous closed M1 must have swept and closed outside opening range.
    above=(float(b.High)>high+.08*atr and float(b.Close)>high)
    below=(float(b.Low)<low-.08*atr and float(b.Close)<low)
    side=("SHORT" if above else "LONG" if below else "BRAK")
    if side=="BRAK":
        return _wait(name,"Zakres 15m gotowy; brak zamkniętego fałszywego wybicia.",
                     checks=(True,False,False),atr=atr)
    back_inside=(float(a.Close)<high-.04*atr and float(a.Close)<float(a.Open)
                 if side=="SHORT" else
                 float(a.Close)>low+.04*atr and float(a.Close)>float(a.Open))
    if not back_inside:
        return _wait(name,"Wybicie wykryte; brak zamknięcia z powrotem w zakresie.",
                     side,checks=(True,True,False),atr=atr)
    entry=float(a.Close)
    if side=="SHORT":
        stop=max(float(a.High),float(b.High))+0.15*atr
        target=(high+low)/2
    else:
        stop=min(float(a.Low),float(b.Low))-0.15*atr
        target=(high+low)/2
    return _finish(name,side,
                   "Badanie: zamknięty fałszywy breakout 15m po 09:30 ET i powrót do środka.",
                   entry,stop,target,spread,min_rr,atr,(True,True,True))


def _ema_pullback_retest(frame, spread, min_rr):
    name=EMA_PULLBACK_RETEST
    if not _ready(frame,spread):
        return _wait(name,"Wymagane >=100 poprawnych zamkniętych M1 UTC.")
    if (frame.index[-1]-frame.index[-2]).total_seconds()!=60:
        return _wait(name,"Przerwa między świecami potwierdzającymi.")
    df=indicators(frame)
    a,b=df.iloc[-1],df.iloc[-2]
    atr=float(a.ATR)
    if not isfinite(atr) or atr<=0:
        return _wait(name,"ATR niegotowy.")
    up=bool(a.EMA9>a.EMA21>a.EMA50 and 45<=a.RSI<=75)
    down=bool(a.EMA9<a.EMA21<a.EMA50 and 25<=a.RSI<=55)
    side="LONG" if up else "SHORT" if down else "BRAK"
    if side=="BRAK":
        return _wait(name,"Brak trendu EMA9/21/50 i filtrowanego RSI.")
    # A swing is old enough to have been confirmed BEFORE the breakout.
    old=df.iloc[:-10].tail(120)
    highs,lows=confirmed_pivots(old,left=2,right=2)
    prior=df.iloc[-8:-2]
    found=False;level=None
    candidates=reversed(highs if side=="LONG" else lows)
    for _,pivot in candidates:
        if side=="LONG":
            breakout=bool((prior.Close>pivot+.05*atr).any()
                          and (prior.Close.shift(1)<=pivot).any())
            retest=(abs(float(b.Low)-pivot)<=.50*atr
                    and abs(float(b.Low)-float(b.EMA21))<=.85*atr)
        else:
            breakout=bool((prior.Close<pivot-.05*atr).any()
                          and (prior.Close.shift(1)>=pivot).any())
            retest=(abs(float(b.High)-pivot)<=.50*atr
                    and abs(float(b.High)-float(b.EMA21))<=.85*atr)
        if breakout and retest:
            found=True;level=float(pivot)
            break
    if not found:
        return _wait(name,"Trend rozpoznany; brak potwierdzonego swingu z wybiciem i retestem EMA21.",
                     side,checks=(True,False,False),atr=atr)
    confirm=(float(a.Close)>max(float(b.High),float(a.EMA9))
             and float(a.Close)>float(a.Open) and float(a.Low)>=level-.6*atr
             if side=="LONG" else
             float(a.Close)<min(float(b.Low),float(a.EMA9))
             and float(a.Close)<float(a.Open) and float(a.High)<=level+.6*atr)
    if not confirm:
        return _wait(name,"Wybicie + retest gotowe, ale brak zamkniętej świecy potwierdzającej.",
                     side,checks=(True,True,False),atr=atr)
    entry=float(a.Close)
    stop=(min(float(a.Low),float(b.Low))-.15*atr if side=="LONG"
          else max(float(a.High),float(b.High))+.15*atr)
    risk=abs(entry-stop)
    target=entry+2*risk if side=="LONG" else entry-2*risk
    from .structure_levels import structural_room
    room=structural_room(frame,side,entry,risk,min_rr)
    if room.blocked:
        return _wait(name,"Potwierdzony swing ogranicza miejsce na TP.",
                     side,checks=(True,True,True),atr=atr)
    return _finish(name,side,
                   "Badanie: trend EMA, wybicie potwierdzonego swingu, retest EMA21 i świeca.",
                   entry,stop,target,spread,min_rr,atr,(True,True,True))


def evaluate_research(frame: pd.DataFrame, strategy: str,
                      spread: float=.6, min_rr: float=1.35):
    """(Decision, 0/3..3/3 progress); NEVER production AUTO vote."""
    if strategy==NY_OPEN_TRAP:
        return _ny_open_trap(frame,spread,min_rr)
    if strategy==EMA_PULLBACK_RETEST:
        return _ema_pullback_retest(frame,spread,min_rr)
    raise ValueError("Nieznana hipoteza badawcza.")
