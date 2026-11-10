"""Visible 0/3–3/3 stage audit for six existing PAPER strategies.

Stages are NOT probabilities and NEVER authorize trading. Every check uses
closed OHLC available at that candle; MTF and mandatory worker vetoes remain
authoritative. Early stages can be present even when the complete setup is WAIT.
"""
from __future__ import annotations

from math import isfinite
from .strategy import indicators

LABELS={
    "DRUGA FALA":("Trend EMA + wcześniejszy impuls","Cofnięcie w okolicy EMA9","Pełny setup, MTF i bramki"),
    "EMA TREND":("Ułożony trend EMA9/21/50","Cena względem EMA9 + RSI","Pełny setup, MTF i bramki"),
    "LIQUIDITY SWEEP":("Test wcześniejszego ekstremum","Powrót ceny do zakresu","Pełny setup, MTF i bramki"),
    "BREAKOUT RETEST":("Poprzednie wybicie poziomu","Retest poziomu","Pełny setup, MTF i bramki"),
    "EMA PULLBACK":("Trend EMA9/21/50","Cofnięcie do EMA21","Pełny setup, MTF i bramki"),
    "VOLATILITY BREAKOUT":("Kompresja zakresu świec","Ekspansja i wybicie","Pełny setup, MTF i bramki"),
}


def _directional_stages(df,name,atr):
    a,b=df.iloc[-1],df.iloc[-2]
    up=bool(a.EMA9>a.EMA21>a.EMA50)
    down=bool(a.EMA9<a.EMA21<a.EMA50)
    if name=="EMA TREND":
        return ((up,up and a.Close>a.EMA9 and 47<=a.RSI<=70),
                (down,down and a.Close<a.EMA9 and 30<=a.RSI<=53))
    if name=="DRUGA FALA":
        prev=df.iloc[-22:-9]
        impulse=float(prev.Close.iloc[-1]-prev.Close.iloc[0])
        correction=df.iloc[-9:-2]
        return ((up and impulse>=1.5*atr,
                 up and impulse>=1.5*atr and correction.Low.min()<=correction.EMA9.min()+.3*atr),
                (down and impulse<=-1.5*atr,
                 down and impulse<=-1.5*atr and correction.High.max()>=correction.EMA9.max()-.3*atr))
    if name=="LIQUIDITY SWEEP":
        high=float(df.High.iloc[-32:-3].max())
        low=float(df.Low.iloc[-32:-3].min())
        return ((a.Low<low-.05*atr,a.Low<low-.05*atr and a.Close>low),
                (a.High>high+.05*atr,a.High>high+.05*atr and a.Close<high))
    if name=="BREAKOUT RETEST":
        high=float(df.High.iloc[-36:-5].max())
        low=float(df.Low.iloc[-36:-5].min())
        return ((b.Close>high+.05*atr,
                 b.Close>high+.05*atr and a.Low<=high+.25*atr and a.Close>high),
                (b.Close<low-.05*atr,
                 b.Close<low-.05*atr and a.High>=low-.25*atr and a.Close<low))
    if name=="EMA PULLBACK":
        past=df.iloc[-6:-1]
        return ((up,up and past.Low.min()<=past.EMA21.max()+.2*atr),
                (down,down and past.High.max()>=past.EMA21.min()-.2*atr))
    if name=="VOLATILITY BREAKOUT":
        earlier=float((df.High-df.Low).iloc[-60:-20].median())
        narrow=float((df.High-df.Low).iloc[-13:-1].median())
        compressed=earlier>0 and narrow>0 and narrow<=earlier*.70
        big=(a.High-a.Low)>=1.35*narrow
        ceiling=float(df.High.iloc[-13:-1].max())
        floor=float(df.Low.iloc[-13:-1].min())
        return ((compressed,compressed and big and a.Close>ceiling+.05*atr),
                (compressed,compressed and big and a.Close<floor-.05*atr))
    return ((False,False),(False,False))


def progress_for_votes(frame,votes,blockers=()):
    """Independent stage display; 3/3 requires raw setup, MTF and global gates.

    Result is a list of serializable dictionaries suitable for the worker's
    durable last_vote_audit and Streamlit views. Never influences AUTO votes.
    """
    ready=(frame is not None and len(frame)>=85
           and frame.index.tz is not None and frame.index.is_monotonic_increasing
           and not frame.index.has_duplicates)
    df=indicators(frame) if ready else None
    atr=float(df.iloc[-1].ATR) if ready else 0.0
    ready=ready and isfinite(atr) and atr>0
    raw_sides={v.get("Setup OHLC") for v in votes
               if v.get("Setup OHLC") in ("LONG","SHORT")}
    conflicting=len(raw_sides)>1
    rows=[]
    for vote in votes:
        name=str(vote.get("Strategia",""))
        if name not in LABELS:
            continue
        raw=str(vote.get("Setup OHLC","WAIT"))
        after=str(vote.get("Po filtrze MTF","WAIT"))
        stages=((False,False),(False,False))
        if ready:
            stages=_directional_stages(df,name,atr)
        choices=[("LONG",stages[0]),("SHORT",stages[1])]
        if raw in ("LONG","SHORT"):
            side=raw
            context,early=next(x for k,x in choices if k==side)
            # An accepted raw setup has already passed its formation checks.
            context,early=True,True
        else:
            choices.sort(key=lambda x:(int(bool(x[1][0]))+int(bool(x[1][1])),x[0]),reverse=True)
            side,(context,early)=choices[0]
            if not context:
                side="BRAK"
            elif choices[0][1]==choices[1][1]:
                side="NIEJEDNOZNACZNY"
        done=bool(raw in ("LONG","SHORT") and after==raw and
                  not blockers and not conflicting)
        count=(1 if context else 0)+(1 if context and early else 0)+(1 if done else 0)
        rows.append({"strategy":name,"side":side,"stage":count,
                     "progress":f"{count}/3",
                     "criteria":[
                         {"name":LABELS[name][0],"ok":bool(context)},
                         {"name":LABELS[name][1],"ok":bool(context and early)},
                         {"name":LABELS[name][2],"ok":done}],
                     "raw":raw,"after_mtf":after,
                     "reason":str(vote.get("Powód",""))[:200]})
    return rows
