"""Read-only A/B audit for legacy candle-high/low vs confirmed swing levels.

An alternative LONG/SHORT is strictly a SHADOW hypothesis. This module NEVER
changes a six-strategy vote, PAPER position, macro filter or broker request.
"""
from __future__ import annotations

from .strategies_pro import decide_any

STUDIED=("EMA TREND","EMA PULLBACK")
SOURCE="Capital.com DEMO REST"
HTFS=("MINUTE_5","MINUTE_15","HOUR")


def _mtf_consensus(views):
    """Reuse the *already evaluated* exact MTF views from the worker.

    Live MTF requires all 4 verified TFs, then >=2 of M5/M15/H1 in one
    direction and no opposite HTF trend. Never infer higher bars from M1.
    """
    if not isinstance(views,(list,tuple)) or len(views)!=4:
        return "WAIT"
    indexed={getattr(x,"timeframe",None):x for x in views}
    if len(indexed)!=4 or set(indexed)!={"MINUTE",*HTFS}:
        return "WAIT"
    if not all(getattr(x,"ready",False) is True for x in indexed.values()):
        return "WAIT"
    direction=[getattr(indexed[k],"trend","UNKNOWN") for k in HTFS]
    if direction.count("UP")>=2 and direction.count("DOWN")==0:
        return "UP"
    if direction.count("DOWN")>=2 and direction.count("UP")==0:
        return "DOWN"
    return "NEUTRAL"


def obstacle_ab_snapshot(frame, spread, views, *, blockers=(), source=SOURCE,
                         epic="US500"):
    """Compare two existing room filters on the same CLOSED OHLC + spread.

    An ALT_SWING direction is not MTF-approved if views unavailable or
    inconsistent, and is NEVER equal to queue_paper or an executed trade.
    """
    result={"source":source,"epic":epic,"status":"UNVERIFIED",
            "candle_utc":None,"mtf":"WAIT","rows":[],"research_only":True}
    if (source!=SOURCE or epic!="US500" or frame is None or len(frame)<85
            or not hasattr(frame,"index") or frame.index.tz is None
            or not frame.index.is_monotonic_increasing
            or frame.index.has_duplicates):
        return result
    candle=frame.index[-1]
    result["candle_utc"]=candle.isoformat()
    mtf=_mtf_consensus(views)
    result["mtf"]=mtf
    rows=[]
    for method in STUDIED:
        old=decide_any(frame,method,spread=spread,obstacle_mode="legacy")
        alt=decide_any(frame,method,spread=spread,obstacle_mode="confirmed_swings")
        is_room=(old.action=="WAIT" and
                 ("opór" in old.reason.lower() or
                  "wsparcie" in old.reason.lower()))
        swing_side=alt.action if alt.action in ("LONG","SHORT") else "WAIT"
        alt_mtf=(swing_side if
                 mtf==("UP" if swing_side=="LONG" else "DOWN")
                 else "WAIT")
        unlocked=bool(is_room and swing_side!="WAIT")
        rows.append({
            "strategy":method,
            "legacy":old.action if old.action in ("LONG","SHORT") else "WAIT",
            "legacy_reason":str(old.reason)[:150],
            "swing":swing_side,
            "swing_reason":str(alt.reason)[:150],
            "swing_after_mtf":alt_mtf,
            "swing_rr":(float(alt.rr) if alt_mtf!="WAIT" and alt.rr is not None
                        else None),
            "legacy_room_veto":is_room,
            "swing_unlocked":unlocked,
            "all_worker_gates_clear":not bool(blockers),
            "NOT_PAPER":True,
        })
    result["rows"]=rows
    result["status"]="OK"
    return result


def obstacle_ab_frequencies(archive, *, limit=120):
    """Aggregate only FUTURE stored, well-formed comparisons (no backfill)."""
    if type(limit) is not int or not 1<=limit<=120:
        raise ValueError("Invalid window")
    seen=set()
    totals={m:{"strategy":m,"scans":0,
               "legacy_room_veto":0,"swing_unlocked_raw":0,
               "swing_after_mtf":0,"swing_with_all_gates":0}
            for m in STUDIED}
    inspected=0
    rows=list(archive or [])[-limit:] if isinstance(archive,list) else []
    for item in rows:
        if not isinstance(item,dict) or item.get("epic")!="US500":
            continue
        key=item.get("key")
        stamp=item.get("candle_utc")
        if not isinstance(key,str) or not isinstance(stamp,str) or key in seen:
            continue
        seen.add(key)
        ab=item.get("obstacle_ab")
        if not isinstance(ab,dict) or ab.get("status")!="OK" or ab.get("candle_utc")!=stamp:
            continue
        if ab.get("source")!=SOURCE or ab.get("epic")!="US500":
            continue
        observations=ab.get("rows")
        if not isinstance(observations,list) or {o.get("strategy")
                for o in observations if isinstance(o,dict)}!=set(STUDIED):
            continue
        inspected+=1
        for v in observations:
            row=totals[v["strategy"]]
            row["scans"]+=1
            if v.get("legacy_room_veto") is True:
                row["legacy_room_veto"]+=1
            if v.get("swing_unlocked") is True:
                row["swing_unlocked_raw"]+=1
                if v.get("swing_after_mtf") in ("LONG","SHORT"):
                    row["swing_after_mtf"]+=1
                    if v.get("all_worker_gates_clear") is True:
                        row["swing_with_all_gates"]+=1
    return {"audited_scans":inspected, "rows":list(totals.values()),
            "note":"Częstotliwości, nie wyniki finansowe ani sygnały PAPER."}
