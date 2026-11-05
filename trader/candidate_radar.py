"""Separate unapproved strategy candidates from actual PAPER positions.

Never count a raw LONG/SHORT as filled or as strategy win-rate evidence.
"""
from __future__ import annotations

def append_candidate(history, snapshot, decision, votes, blockers, limit=120):
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
    row={"key":key,"candle_utc":stamp.isoformat(),"epic":snapshot.epic,
         "timeframe":snapshot.resolution,"raw_candidates":raw,
         "decision":str(getattr(decision,"action","WAIT")),
         "blockers":[str(x)[:90] for x in (blockers or [])],
         "note":"RESEARCH ONLY — brak wejścia i brak wyniku"}
    return (rows+[row])[-max(1,min(500,int(limit))):]
