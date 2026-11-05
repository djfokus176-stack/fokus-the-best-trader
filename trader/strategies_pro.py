"""Four additional OHLC-only *hypotheses* for PAPER research and replay.

Signals are not orders or proven alpha. Each evaluation receives only bars
closed at that point in time. Costs and nearby obstacles may veto a setup.
"""
from __future__ import annotations
import math
import pandas as pd
from .strategy import Decision, decide, indicators

LEGACY = ("DRUGA FALA", "EMA TREND")
EXTRA = ("LIQUIDITY SWEEP", "BREAKOUT RETEST", "EMA PULLBACK", "VOLATILITY BREAKOUT")
ALL_STRATEGIES = LEGACY + EXTRA


def decide_any(frame: pd.DataFrame, strategy="DRUGA FALA", spread:float=.6,
               min_rr:float=1.35) -> Decision:
    if strategy in LEGACY:
        return decide(frame,strategy,spread=spread,min_rr=min_rr)
    if strategy not in EXTRA:
        return Decision("WAIT",strategy,"Nieznana strategia: brak sygnału.")
    if frame is None or len(frame)<85 or spread<0 or not math.isfinite(spread):
        return Decision("WAIT",strategy,"Brak 85 zamkniętych świec lub błędny spread.")
    df=indicators(frame)
    a,b=df.iloc[-1],df.iloc[-2]
    atr=float(a.ATR)
    if not math.isfinite(atr) or atr<=0:
        return Decision("WAIT",strategy,"ATR niedostępny.")
    if spread>max(1.2,atr*.4):
        return Decision("WAIT",strategy,"Koszt spreadu zbyt wysoki względem ATR.",atr=atr)
    bias=("UP" if a.EMA9>a.EMA21>a.EMA50 else
          "DOWN" if a.EMA9<a.EMA21<a.EMA50 else "NEUTRAL")
    side=None
    reason=""
    pivot=None

    if strategy=="LIQUIDITY SWEEP":
        # Older confirmed local extrema, excluding the most recent 3 bars.
        high=float(df.High.iloc[-32:-3].max())
        low=float(df.Low.iloc[-32:-3].min())
        if a.High>high+0.05*atr and a.Close<high and a.Close>a.Low+0.25*(a.High-a.Low):
            side="SHORT";pivot=float(a.High)
            reason="Knot ponad dawnym maksimum i zamknięcie z powrotem poniżej."
        elif a.Low<low-0.05*atr and a.Close>low and a.Close<a.High-0.25*(a.High-a.Low):
            side="LONG";pivot=float(a.Low)
            reason="Knot poniżej dawnego minimum i powrót ponad poziom."
    elif strategy=="BREAKOUT RETEST":
        level_high=float(df.High.iloc[-36:-5].max())
        level_low=float(df.Low.iloc[-36:-5].min())
        if b.Close>level_high+0.05*atr and a.Low<=level_high+.25*atr and a.Close>level_high and a.Close>b.Close-.5*atr:
            side="LONG";pivot=min(float(a.Low),level_high)
            reason="Wcześniejsze wybicie oporu, test poziomu i zamknięcie powyżej."
        elif b.Close<level_low-.05*atr and a.High>=level_low-.25*atr and a.Close<level_low and a.Close<b.Close+.5*atr:
            side="SHORT";pivot=max(float(a.High),level_low)
            reason="Wcześniejsze wybicie wsparcia, retest i zamknięcie poniżej."
    elif strategy=="EMA PULLBACK":
        pullback=df.iloc[-6:-1]
        if bias=="UP" and pullback.Low.min()<=pullback.EMA21.max()+.2*atr and a.Close>a.EMA9 and a.Close>a.Open and 40<a.RSI<76:
            side="LONG";pivot=float(pullback.Low.min())
            reason="Trend wzrostowy EMA, cofnięcie do EMA21, potwierdzona świeca wzrostowa."
        elif bias=="DOWN" and pullback.High.max()>=pullback.EMA21.min()-.2*atr and a.Close<a.EMA9 and a.Close<a.Open and 24<a.RSI<60:
            side="SHORT";pivot=float(pullback.High.max())
            reason="Trend spadkowy EMA, cofnięcie do EMA21, potwierdzona świeca spadkowa."
    elif strategy=="VOLATILITY BREAKOUT":
        earlier=(df.High-df.Low).iloc[-60:-20].median()
        compressed=(df.High-df.Low).iloc[-13:-1].median()
        ceiling=float(df.High.iloc[-13:-1].max())
        floor=float(df.Low.iloc[-13:-1].min())
        if earlier>0 and compressed<=earlier*.70 and a.High-a.Low>=1.35*compressed:
            if a.Close>ceiling+.05*atr:
                side="LONG";pivot=float(a.Low)
                reason="Historyczna kompresja świec, ekspansja i zamknięcie ponad zakresem."
            elif a.Close<floor-.05*atr:
                side="SHORT";pivot=float(a.High)
                reason="Historyczna kompresja świec, ekspansja i zamknięcie poniżej zakresu."

    if side is None:
        return Decision("WAIT",strategy,"Brak pełnego układu; nie wymuszam wejścia.",atr=round(atr,2),bias=bias)
    entry=float(a.Close)
    prior=df.iloc[-12:-1]
    if side=="LONG":
        stop=min(float(pivot)-.12*atr,float(prior.Low.min())-.08*atr,entry-1.1*atr)
        risk=entry-stop
        target=entry+2*risk
        obstacles=df.High.iloc[-75:-8]
        blockers=obstacles[obstacles>entry]
        if len(blockers) and float(blockers.min())-entry<min_rr*risk:
            return Decision("WAIT",strategy,"Zbyt bliski potwierdzony opór (room-to-target).",atr=round(atr,2),bias=bias)
    else:
        stop=max(float(pivot)+.12*atr,float(prior.High.max())+.08*atr,entry+1.1*atr)
        risk=stop-entry
        target=entry-2*risk
        obstacles=df.Low.iloc[-75:-8]
        blockers=obstacles[obstacles<entry]
        if len(blockers) and entry-float(blockers.max())<min_rr*risk:
            return Decision("WAIT",strategy,"Zbyt bliskie potwierdzone wsparcie (room-to-target).",atr=round(atr,2),bias=bias)
    if risk<=spread*1.5 or (2*risk-spread)/(risk+spread)<min_rr:
        return Decision("WAIT",strategy,"Zbyt mały stosunek zysku do ryzyka po spreadzie.",atr=round(atr,2),bias=bias)
    return Decision(side,strategy,reason,round(entry,2),round(stop,2),
                    round(target,2),round((2*risk-spread)/(risk+spread),2),
                    round(atr,2),bias)
