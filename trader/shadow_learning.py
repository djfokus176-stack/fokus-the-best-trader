"""Forward-only independent SHADOW PAPER ledger per strategy (no broker orders).

Research-only pseudo-fills: next CLOSED M1 reveals its hypothetical OPEN.
Same conservative bid/ask spread + slippage model as fixed PAPER lifecycle.
Only NEW consecutive confirmed candles advance state; gaps invalidate active
studies rather than backfilling fictitious fills. Each strategy has its OWN
active slot, so winner selection is not biased by the deployed AUTO picker.
Never uses this-bar outcomes to rank the candidate on that same bar.
"""
from __future__ import annotations
from datetime import timedelta
from math import isfinite, sqrt
import pandas as pd
from .strategies_pro import ALL_STRATEGIES,decide_any

MAX_HISTORY=240
MIN_TRAIN_AND_HOLDOUT=100
MAX_BARS=20
SLIPPAGE=.25


def _blank():
    return {"schema":1,"last_candle_utc":None,"active":{},
            "closed":{name:[] for name in ALL_STRATEGIES},
            "invalidated":{name:0 for name in ALL_STRATEGIES},"gaps":0}


def _close_pos(active, candle, utc):
    side=active["side"]
    stop,target=float(active["stop"]),float(active["target"])
    half=float(active["spread"])/2
    slip=SLIPPAGE
    start=float(active["entry_exec"])
    if side=="LONG":
        hit_sl=float(candle.Low)<=stop
        hit_tp=float(candle.High)>=target
    else:
        hit_sl=float(candle.High)>=stop
        hit_tp=float(candle.Low)<=target
    active["bars"]+=1
    if hit_sl:
        exit_mid=(min(stop,float(candle.Open)) if side=="LONG"
                  else max(stop,float(candle.Open)))
        status="CLOSED_SL"
    elif hit_tp:
        exit_mid=target
        status="CLOSED_TP"
    elif active["bars"]>=MAX_BARS:
        exit_mid=float(candle.Close)
        status="CLOSED_TIMEOUT"
    else:
        return None
    executable=(exit_mid-half-slip if side=="LONG"
                else exit_mid+half+slip)
    pnl=(executable-start if side=="LONG" else start-executable)
    risk=abs(float(active["entry_mid"])-stop)
    if risk<=0:
        return None
    return {"utc":utc,"side":side,"status":status,
            "pnl_pts":round(pnl,3),"r":round(pnl/risk,5)}


def advance_shadow(state, frame, votes, blockers=(), *, spread):
    """Update each strategy once per closed minute, no historical look-ahead.

    Confidence is evaluated only from prior completed independent trials.
    All accepted setups have already passed MTF. Global blockers + raw
    opposite conflicts prevent hypothetical new queues just like AUTO.
    """
    data=state if isinstance(state,dict) and state.get("schema")==1 else _blank()
    if frame is None or len(frame)<85 or frame.index.tz is None:
        return data
    stamp=frame.index[-1]
    current=stamp.isoformat()
    last=data.get("last_candle_utc")
    previous=pd.Timestamp(last) if last else None
    if previous is not None and stamp<=previous:
        return data
    row=frame.iloc[-1]
    active=dict(data.get("active") or {})
    closed=dict(data.get("closed") or {})
    invalidated=dict(data.get("invalidated") or {})
    if previous is not None and stamp!=previous+pd.Timedelta(minutes=1):
        for name in active:
            invalidated[name]=invalidated.get(name,0)+1
        active={}
        data["gaps"]=int(data.get("gaps",0))+1
    else:
        for name,pos in tuple(active.items()):
            if pos.get("status")=="PENDING":
                if previous is None or pd.Timestamp(pos["setup_utc"])+pd.Timedelta(minutes=1)!=stamp:
                    invalidated[name]=invalidated.get(name,0)+1
                    del active[name]
                    continue
                entry_mid=float(row.Open)
                stop,target=float(pos["stop"]),float(pos["target"])
                if not ((stop<entry_mid<target) if pos["side"]=="LONG"
                        else (target<entry_mid<stop)):
                    invalidated[name]=invalidated.get(name,0)+1
                    del active[name]
                    continue
                pos["entry_mid"]=entry_mid
                pos["entry_exec"]=entry_mid+(float(pos["spread"])/2+SLIPPAGE)*(
                    1 if pos["side"]=="LONG" else -1)
                pos["status"]="OPEN"
                pos["bars"]=0
            result=_close_pos(pos,row,current)
            if result is not None:
                closed[name]=(closed.get(name,[])+[result])[-MAX_HISTORY:]
                del active[name]
    raw_sides={str(v.get("Setup OHLC","WAIT")) for v in votes
               if v.get("Setup OHLC") in ("LONG","SHORT")}
    conflict=len(raw_sides)>1
    if not blockers and not conflict and isfinite(float(spread)) and spread>=0:
        for vote in votes:
            name=vote.get("Strategia")
            side=vote.get("Po filtrze MTF")
            if name not in ALL_STRATEGIES or side not in ("LONG","SHORT") or name in active:
                continue
            d=decide_any(frame,name,spread=spread)
            if d.action!=side or d.stop is None or d.target is None or d.entry is None:
                continue
            stop,target,entry=float(d.stop),float(d.target),float(d.entry)
            if not all(isfinite(x) for x in (stop,target,entry)):
                continue
            if not ((stop<entry<target) if side=="LONG" else
                    (target<entry<stop)):
                continue
            active[name]={"status":"PENDING","side":side,"setup_utc":current,
                          "stop":stop,"target":target,"spread":float(spread)}
    data.update(last_candle_utc=current,active=active,closed=closed,
                invalidated=invalidated)
    return data


def shadow_scorecard(state):
    """Chronological held-out comparison of six independently logged methods.

    Minimum >=100 CLOSED forward SHADOW examples per strategy, >=30 recent
    holdout; lower95 R > 0 to call ranking eligible. Repeated comparison of
    this holdout is exploratory, not independent live proof.
    """
    state=state if isinstance(state,dict) else {}
    history=state.get("closed") or {}
    rows=[]
    for name in ALL_STRATEGIES:
        outcomes=[r for r in history.get(name,[]) if isfinite(float(r.get("r",float("nan"))))]
        n=len(outcomes)
        split=int(n*.70)
        train=outcomes[:split]
        test=outcomes[split:]
        recent=[float(x["r"]) for x in test]
        mean=sum(recent)/len(recent) if recent else None
        if len(recent)>=2:
            variance=sum((v-mean)**2 for v in recent)/(len(recent)-1)
            lower=mean-1.96*sqrt(variance/len(recent))
        else:
            lower=None
        qualified=(n>=MIN_TRAIN_AND_HOLDOUT and len(test)>=30
                   and lower is not None and lower>0)
        rows.append({"strategy":name,"closed":n,
            "train":len(train),"holdout":len(test),
            "win_rate_pct":round(100*sum(x["r"]>0 for x in outcomes)/n,1) if n else None,
            "mean_r_holdout":round(mean,4) if mean is not None else None,
            "lower95_r_holdout":round(lower,4) if lower is not None else None,
            "eligible":qualified,"invalidated":int((state.get("invalidated") or {}).get(name,0))})
    leaders=sorted((r for r in rows if r["eligible"]),
                   key=lambda r:(-r["lower95_r_holdout"],r["strategy"]))
    return {"status":"FORWARD_SHADOW_RESEARCH_NOT_LIVE_PROOF",
            "last_candle_utc":state.get("last_candle_utc"),
            "gap_count":int(state.get("gaps",0)),
            "minimum_closed_per_strategy":MIN_TRAIN_AND_HOLDOUT,
            "leader":leaders[0]["strategy"] if leaders else None,
            "strategies":rows}
