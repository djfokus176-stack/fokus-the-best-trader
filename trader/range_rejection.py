"""Extra strictly research-only RANGE REJECTION hypothesis (not AUTO).

No volume / true orderbook is available from Capital OHLC, so this is a
range-bound rejection with causal prior highs/lows and validated candle.
It is NOT included among deployable AUTO strategies or new PAPER entries
until independent forward evidence exists.
"""
from __future__ import annotations
from math import isfinite
from .strategy import Decision,indicators
from .market_dna import analyze_market

NAME="RANGE REJECTION"
RESEARCH_ONLY=True


def decide_range_rejection(frame,spread=.6,min_rr=1.35):
    no=lambda why: Decision("WAIT",NAME,why)
    if frame is None or len(frame)<100 or spread<0 or not isfinite(spread):
        return no("Brak 100 zamkniętych M1 lub niepoprawny spread.")
    market=analyze_market(frame)
    if market.regime not in ("KONSOLIDACJA / MAŁA EFEKTYWNOŚĆ","MIESZANY / PRZEJŚCIOWY"):
        return no("Strategia badawcza tylko dla konsolidacji, nie silnego trendu.")
    if market.efficiency>.23:
        return no("Rynek nadal zbyt kierunkowy dla odrzucenia granicy zakresu.")
    df=indicators(frame)
    a=df.iloc[-1]
    atr=float(a.ATR)
    if not isfinite(atr) or atr<=0 or spread>max(1.2,atr*.4):
        return no("Niedostępny ATR lub spread za duży względem zmienności.")
    floor=float(df.Low.iloc[-45:-1].min())
    ceil=float(df.High.iloc[-45:-1].max())
    if ceil-floor<3*atr:
        return no("Za mały historyczny zakres względem ATR i kosztów.")
    center=(floor+ceil)/2
    side=None
    if (a.Low<=floor+.15*atr and a.Close>floor+.25*atr
        and a.Close>a.Open and 25<=a.RSI<=45):
        side="LONG"
        stop=min(float(a.Low),floor)-.20*atr
        target=center
    elif (a.High>=ceil-.15*atr and a.Close<ceil-.25*atr
          and a.Close<a.Open and 55<=a.RSI<=78):
        side="SHORT"
        stop=max(float(a.High),ceil)+.20*atr
        target=center
    else:
        return no("Brak zamkniętej świecy odrzucającej dolną/górną granicę konsolidacji.")
    entry=float(a.Close)
    if not ((stop<entry<target) if side=="LONG" else (target<entry<stop)):
        return no("Niepoprawna geometria SL/TP do środka zakresu.")
    risk=abs(entry-stop)
    reward=abs(target-entry)
    rr=(reward-spread)/(risk+spread) if risk>0 else -1
    if not isfinite(rr) or rr<min_rr:
        return no("Zbyt mało miejsca do środka zakresu po spreadzie (RR).")
    return Decision(side,NAME,
        "SHADOW: odrzucenie historycznej bandy i możliwy powrót do środka zakresu; bez wejścia AUTO.",
        round(entry,2),round(stop,2),round(target,2),round(rr,2),round(atr,2),
        "RANGE")
