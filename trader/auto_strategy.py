"""FOKU$ AUTO — six independent closed-bar PAPER hypotheses.

This is a deterministic screening/consensus policy, NOT a trained strategy
selector, calibrated win probability, financial recommendation or order.
In conflicting/insufficient conditions return WAIT, never invent entries.
"""
from __future__ import annotations
from dataclasses import replace
from .strategy import Decision
from .strategies_pro import ALL_STRATEGIES, decide_any
from .mtf import filter_mtf_decision

AUTO_MODE="AUTO — 6 STRATEGII"
MIN_AGREEMENT=2

def evaluate_auto(frame,spread,snapshots=None,*,asof=None,use_mtf=True):
    """Return chosen PAPER hypothesis (or WAIT) and transparent six-row audit.

    At least two independently named strategies must agree on direction;
    even one opposing raw setup makes the joint hypothesis WAIT.
    The MTF veto is applied *before* choosing among candidates. Never sum
    correlated hypotheses into confidence/probability or declare "best".
    """
    snapshots=snapshots or {}
    rows=[]
    approved=[]
    raw_sides=set()
    for name in ALL_STRATEGIES:
        raw=decide_any(frame,name,spread=spread)
        if raw.action in ("LONG","SHORT"):
            raw_sides.add(raw.action)
        screened,_=filter_mtf_decision(raw,snapshots,asof=asof) if use_mtf else (raw,[])
        rows.append({"Strategia":name,"Setup OHLC":raw.action,
                     "Po filtrze MTF":screened.action,
                     "RR":raw.rr if raw.action in ("LONG","SHORT") else None,
                     "Powód":screened.reason if screened.action!=raw.action else raw.reason})
        if screened.action in ("LONG","SHORT"):
            approved.append(screened)
    atr=next((v.atr for v in approved if v.atr is not None),None)
    if len(raw_sides)>1:
        return (Decision("WAIT",AUTO_MODE,
            "Konflikt LONG/SHORT między strategiami — nie wybieram kierunku.",
            atr=atr),rows)
    directions={d.action for d in approved}
    if len(directions)>1:
        return (Decision("WAIT",AUTO_MODE,
            "Konflikt kierunków po filtrach — brak przewagi.",atr=atr),rows)
    if len(approved)<MIN_AGREEMENT:
        return (Decision("WAIT",AUTO_MODE,
            f"Po filtrach MTF zgodnych setupów: {len(approved)}/{MIN_AGREEMENT}. "
            "Nie wymuszam transakcji PAPER.",atr=atr),rows)
    # Transparent deterministic tie-break (larger estimated RR, then name).
    # Not evidence this is an optimal strategy! Retain true source name.
    selected=sorted(approved,key=lambda d:(-float(d.rr or 0),d.strategy))[0]
    return (replace(selected,reason=(
        f"AUTO PAPER: {len(approved)} zgodne strategie: "
        +", ".join(d.strategy for d in approved)
        +f". Wybrano {selected.strategy} po deklarowanym RR; "
         "bez potwierdzonej przewagi statystycznej. "+selected.reason)),rows)
