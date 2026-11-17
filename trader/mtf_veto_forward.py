"""Independent FORWARD-only study of raw PAPER signals vetoed or accepted by MTF.

No new orders, no signals invented from watch 2/3, no broker connections.
A raw strategy signal with valid SL/TP is followed for up to 20 consecutive
CLOSED M1 candles and assigned to its known-at-setup MTF outcome. This is
observational, NOT a randomized causal estimate of MTF usefulness.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite, sqrt
import pandas as pd

from .strategies_pro import ALL_STRATEGIES, decide_any

MAX_CLOSED=240
MAX_HOLDING=20
SLIPPAGE=.25
EXPECTED_STEP=pd.Timedelta(minutes=1)
SOURCE="Capital.com DEMO REST"


def _new():
    return {"schema":1,"last_candle_utc":None,"active":{},
            "closed":[],"invalidated":0,"gaps":0,
            "skipped_blocked":0,"skipped_busy":0,"started":0}


def _price(x):
    try:
        n=float(x)
    except (ValueError,TypeError,OverflowError):
        return None
    return n if isfinite(n) else None


def _stamp(x):
    try:
        t=pd.Timestamp(x)
    except (ValueError,TypeError,OverflowError):
        return None
    if pd.isna(t) or t.tzinfo is None:
        return None
    return t.tz_convert("UTC")


def _settle(position, bar, stamp):
    """Consume only THIS newly closed candle, with stop-before-target."""
    side=position["side"]
    opening=float(bar.Open)
    high=float(bar.High)
    low=float(bar.Low)
    close=float(bar.Close)
    if not all(isfinite(n) for n in (opening,high,low,close)):
        return None,"INVALID"
    if low>min(opening,close) or high<max(opening,close) or low>high:
        return None,"INVALID"
    if position["status"]=="PENDING":
        if _stamp(position["setup_utc"])+EXPECTED_STEP!=stamp:
            return None,"INVALID"
        stop,target=position["stop"],position["target"]
        if not (stop<opening<target if side=="LONG"
                else target<opening<stop):
            return None,"INVALID"
        # The next bar OPEN is only observable once the NEXT bar closes:
        # this is a post-hoc synthetic fill, never a live executed trade.
        cost=position["spread"]/2+SLIPPAGE
        position["entry_mid"]=opening
        position["entry_exec"]=opening+(cost if side=="LONG" else -cost)
        position["risk"]=abs(opening-stop)
        position["status"]="OPEN"
        position["bars"]=0
    stop,target=position["stop"],position["target"]
    if side=="LONG":
        touched_stop=low<=stop
        touched_target=high>=target
    else:
        touched_stop=high>=stop
        touched_target=low<=target
    position["bars"]+=1
    if touched_stop:
        exit_mid=min(stop,opening) if side=="LONG" else max(stop,opening)
        result="SL"
    elif touched_target:
        exit_mid=target
        result="TP"
    elif position["bars"]>=MAX_HOLDING:
        exit_mid=close
        result="TIMEOUT"
    else:
        return position,None
    cost=position["spread"]/2+SLIPPAGE
    exit_exec=exit_mid+(-cost if side=="LONG" else cost)
    pnl=(exit_exec-position["entry_exec"] if side=="LONG"
         else position["entry_exec"]-exit_exec)
    risk=position["risk"]
    if risk<=0 or not isfinite(pnl):
        return None,"INVALID"
    record={
        "strategy":position["strategy"],
        "side":side,
        "mtf":position["mtf"],
        "setup_utc":position["setup_utc"],
        "closed_utc":stamp.isoformat(),
        "exit":result,
        "pnl_pts":round(pnl,3),
        "r":round(pnl/risk,5),
        "bars":position["bars"],
        "spread":position["spread"],
        "slippage_per_side":SLIPPAGE,
    }
    return None,record


def advance_mtf_comparison(state, frame, votes, blockers=(), *,
                           spread, source=SOURCE, epic="US500"):
    """Advance only once per NEW consecutive closed M1. NO replay/backfill.

    Study only raw candidates whose setup already has real stop/target, not
    2/3 progress or OBSERVE hints. Skip globally unsafe/blocked cycles.
    """
    data=state if isinstance(state,dict) and state.get("schema")==1 else _new()
    if (source!=SOURCE or epic!="US500" or frame is None
            or not isinstance(frame,pd.DataFrame) or len(frame)<85
            or not isinstance(frame.index,pd.DatetimeIndex)
            or frame.index.tz is None
            or not frame.index.is_monotonic_increasing
            or frame.index.has_duplicates):
        return data
    price_spread=_price(spread)
    if price_spread is None or price_spread<0:
        return data
    stamp=frame.index[-1].tz_convert("UTC")
    previous=_stamp(data.get("last_candle_utc")) if data.get("last_candle_utc") else None
    if previous is not None and stamp<=previous:
        return data
    if previous is not None and stamp!=previous+EXPECTED_STEP:
        data["invalidated"]=int(data.get("invalidated",0))+len(data.get("active") or {})
        data["active"]={}
        data["gaps"]=int(data.get("gaps",0))+1
        data["last_candle_utc"]=stamp.isoformat()
        # Do not seed signals on an interval following a missing bar.
        return data
    active=dict(data.get("active") or {})
    closed=list(data.get("closed") or [])
    for name,position in list(active.items()):
        nxt,result=_settle(position.copy(),frame.iloc[-1],stamp)
        if result=="INVALID":
            active.pop(name,None)
            data["invalidated"]=int(data.get("invalidated",0))+1
        elif isinstance(result,dict):
            closed.append(result)
            active.pop(name,None)
        elif nxt is not None:
            active[name]=nxt
    data["closed"]=closed[-MAX_CLOSED:]
    data["last_candle_utc"]=stamp.isoformat()
    data["active"]=active
    if blockers:
        data["skipped_blocked"]=int(data.get("skipped_blocked",0))+1
        return data
    # Input votes were calculated on the same already-closed candle as frame.
    sides={v.get("Setup OHLC") for v in (votes or [])
           if isinstance(v,dict) and v.get("Setup OHLC") in ("LONG","SHORT")}
    if len(sides)>1:
        # Preserve production AUTO conflict veto in both research cohorts.
        return data
    for vote in votes or []:
        if not isinstance(vote,dict):
            continue
        name=vote.get("Strategia")
        side=vote.get("Setup OHLC")
        if name not in ALL_STRATEGIES or side not in ("LONG","SHORT"):
            continue
        if name in active:
            data["skipped_busy"]=int(data.get("skipped_busy",0))+1
            continue
        after=vote.get("Po filtrze MTF")
        if after not in ("WAIT",side):
            # Inconsistent provenance, do not manufacture a cohort.
            continue
        d=decide_any(frame,name,spread=price_spread)
        if d.action!=side:
            continue
        entry,stop,target=(_price(d.entry),_price(d.stop),_price(d.target))
        if None in (entry,stop,target):
            continue
        if not (stop<entry<target if side=="LONG" else target<entry<stop):
            continue
        active[name]={
            "strategy":name,"side":side,
            "mtf":"PASSED" if after==side else "VETOED",
            "setup_utc":stamp.isoformat(),"status":"PENDING",
            "stop":stop,"target":target,
            "spread":price_spread,"bars":0,
        }
        data["started"]=int(data.get("started",0))+1
    data["active"]=active
    return data


def mtf_comparison_report(state):
    """Small-sample descriptive summaries; never claim statistical edge."""
    data=state if isinstance(state,dict) and state.get("schema")==1 else _new()
    records=[r for r in data.get("closed",[])
             if isinstance(r,dict) and r.get("strategy") in ALL_STRATEGIES
             and r.get("mtf") in ("PASSED","VETOED")
             and _price(r.get("pnl_pts")) is not None
             and _price(r.get("r")) is not None]
    groups=defaultdict(list)
    for record in records:
        groups[(record["strategy"],record["mtf"])].append(record)
        groups[("ALL",record["mtf"])].append(record)
    result=[]
    for strategy in ("ALL",*ALL_STRATEGIES):
        for policy in ("PASSED","VETOED"):
            rows=groups[(strategy,policy)]
            n=len(rows)
            pnl=[float(r["pnl_pts"]) for r in rows]
            rs=[float(r["r"]) for r in rows]
            wins=sum(v>0 for v in pnl)
            result.append({
                "strategy":strategy,
                "mtf":policy,
                "closed":n,
                "wins":wins,
                "win_rate_pct":round(wins*100/n,1) if n else None,
                "sum_pts":round(sum(pnl),2) if n else None,
                "mean_pts":round(sum(pnl)/n,3) if n else None,
                "mean_r":round(sum(rs)/n,4) if n else None,
                # Very small samples are descriptive, not statistical proof.
                "research_only":True,
            })
    return {
        "status":"FORWARD_ONLY_OBSERVATIONAL_NOT_TRADEABLE",
        "last_candle_utc":data.get("last_candle_utc"),
        "started":int(data.get("started",0)),
        "active":len(data.get("active") or {}),
        "invalidated":int(data.get("invalidated",0)),
        "gaps":int(data.get("gaps",0)),
        "skipped_blocked":int(data.get("skipped_blocked",0)),
        "skipped_busy":int(data.get("skipped_busy",0)),
        "closed":len(records),
        "groups":result,
        "minimum_per_cohort_for_exploration":100,
        "limit_note":"Wyniki są obserwacyjne i skorelowane; bez eksperymentu randomizowanego ani gwarancji zysku.",
    }
