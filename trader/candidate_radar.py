"""Separate unapproved strategy candidates from actual PAPER positions.

Never count a raw LONG/SHORT as filled or as strategy win-rate evidence.
"""
from __future__ import annotations
from .strategies_pro import ALL_STRATEGIES

def append_candidate(history, snapshot, decision, votes, blockers, limit=120, *, progress=None):
    rows=list(history or [])
    stamp=getattr(snapshot,"confirmed_utc",None)
    if stamp is None:
        return rows[-limit:]
    key="|".join((str(snapshot.source),str(snapshot.epic),
                  str(snapshot.resolution),stamp.isoformat()))
    if any(x.get("key")==key for x in rows):
        return rows[-limit:]
    raw=[{"strategy":str(x.get("Strategia",""))[:70],
          "direction":str(x.get("Setup OHLC",""))[:8],
          "after_mtf":str(x.get("Po filtrze MTF",""))[:8],
          "rr":x.get("RR"),
          "reason":str(x.get("Powód",""))[:180]}
         for x in (votes or []) if x.get("Setup OHLC") in ("LONG","SHORT")]
    stage_map={p.get("strategy"):p for p in (progress or [])
               if isinstance(p,dict) and p.get("strategy") in ALL_STRATEGIES}
    # Audit-only: capture WHY each strategy said WAIT, not just those that
    # produced raw LONG/SHORT. Kept to 120 scans by the existing ring buffer.
    # The two additional research comparisons are excluded deliberately.
    diagnostic=[]
    for v in votes or []:
        name=v.get("Strategia")
        if name not in ALL_STRATEGIES:
            continue
        step=stage_map.get(name,{})
        level=step.get("stage")
        if type(level) is not int or level not in (0,1,2,3):
            level=None
        diagnostic.append({
            "strategy":name,
            "raw":str(v.get("Setup OHLC","WAIT"))[:8],
            "after_mtf":str(v.get("Po filtrze MTF","WAIT"))[:8],
            "reason":str(v.get("Powód",""))[:150],
            "stage":level,
            "stage_side":str(step.get("side","BRAK"))[:20],
        })
    row={"key":key,"candle_utc":stamp.isoformat(),"epic":snapshot.epic,
         "timeframe":snapshot.resolution,"raw_candidates":raw,
         "strategy_audit":diagnostic[:6],
         "decision":str(getattr(decision,"action","WAIT")),
         "blockers":[str(x)[:90] for x in (blockers or [])],
         "note":"RESEARCH ONLY — brak wejścia i brak wyniku"}
    return (rows+[row])[-max(1,min(500,int(limit))):]
