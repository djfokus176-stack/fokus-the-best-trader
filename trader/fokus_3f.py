"""FOKU$ 3F — FALA / FILTR / FINAŁ. Research only, M15 closed candles.

Reuses existing confirmed 2-left/2-right pivots and M15 validation.
Not part of six AUTO votes, broker execution, or PAPER position lifecycle.
A replayed next-bar OPEN is a retrospective MODEL fill, never broker proof.
"""
from __future__ import annotations

from datetime import time
from math import isfinite
from zoneinfo import ZoneInfo
import pandas as pd
from .market_dna import confirmed_pivots
from .strategy import indicators
from .wave_reversal import validate_closed_m15

NAME="FOKU$ 3F (BADANIE)"
VERSION="fokus_3f_research_v1"
SOURCE="Capital.com DEMO REST"
NY=ZoneInfo("America/New_York")
FIRST=time(9,45)
LAST=time(16,0)
MAX_WAIT=8
MAX_HOLD=8
RESOLVED=("TP","SL","TIMEOUT","SESSION_TIMEOUT")


def _nyday(stamp):
    return stamp.tz_convert(NY).date().isoformat()


def _cash(stamp):
    local=stamp.tz_convert(NY)
    return local.weekday()<5 and FIRST<=local.time()<=LAST


def _chunks(frame):
    """Only uninterrupted M15 NY regular-session runs; never bridge gaps."""
    chunks=[];run=[]
    for i,stamp in enumerate(frame.index):
        if not _cash(stamp):
            if run:chunks.append(run);run=[]
            continue
        if run and (_nyday(stamp)!=_nyday(frame.index[run[-1]]) or
                    stamp-frame.index[run[-1]]!=pd.Timedelta(minutes=15)):
            chunks.append(run);run=[]
        run.append(i)
    if run:chunks.append(run)
    return chunks


def _validate(frame,spread,slippage,rr):
    validate_closed_m15(frame)
    if any(not isinstance(x,(int,float)) or not isfinite(x)
           for x in (spread,slippage,rr)):
        raise ValueError("3F: invalid risk/cost type")
    if spread<0 or slippage<0 or rr not in (1.5,1.8,2.0):
        raise ValueError("3F: invalid cost/TP")
    if "Spread" in frame:
        s=pd.to_numeric(frame.Spread,errors="coerce")
        if s.isna().any() or not s.map(isfinite).all() or (s<0).any():
            raise ValueError("3F: invalid recorded spread")


def _spread(frame,i,default):
    if "Spread" in frame:
        return float(frame.Spread.iloc[i]),"RECORDED_LAST_CLOSED_SPREAD"
    return float(default),"FIXED_SPREAD_ASSUMPTION"


def _signal(frame,features,i,start,*,spread,slippage,rr):
    """As-of M15 signal. Decision candle cannot confirm its own pivots."""
    stamp=frame.index[i]
    wait={"strategy":NAME,"research_side":"WAIT","trade_permission":"WAIT",
          "version":VERSION,"signal_utc":stamp.isoformat(),
          "session_ny":_nyday(stamp),"reason":"BRAK UKŁADU 3F"}
    if i-start<12 or not _cash(stamp):
        return wait
    atr=float(features.ATR.iloc[i])
    if not isfinite(atr) or atr<=0:
        return {**wait,"reason":"BRAK ATR14"}
    # Earlier session candles only: 2 right neighbors were already CLOSED
    # by i-1. Reuse the canonical pivot detector from MARKET DNA.
    highs,lows=confirmed_pivots(frame.iloc[start:i],left=2,right=2)
    prev=float(features.Close.iloc[i-1]);close=float(features.Close.iloc[i])
    ema=float(features.EMA21.iloc[i]);ema4=float(features.EMA21.iloc[i-4])
    spr,spr_source=_spread(frame,i,spread)
    cost=spr+2*slippage
    candidates=[]
    for side,pivots in (("SHORT",highs),("LONG",lows)):
        if len(pivots)<3:continue
        seq=[(start+j,float(v)) for j,v in pivots[-3:]]
        (p1,a),(p2,b),(p3,c)=seq
        if (i<=p3+2 or i>p3+2+MAX_WAIT or
                max(a,b,c)-min(a,b,c)>.35*atr):
            continue
        between=frame.iloc[p2+1:p3]
        if between.empty:continue
        if side=="SHORT":
            level=float(between.Low.min())
            threshold=level-.10*atr
            match=(prev>=threshold and close<threshold and
                   close<ema and ema<=ema4)
            stop=max(b,c)+.15*atr
            risk=stop-close
            target=close-rr*risk
        else:
            level=float(between.High.max())
            threshold=level+.10*atr
            match=(prev<=threshold and close>threshold and
                   close>ema and ema>=ema4)
            stop=min(b,c)-.15*atr
            risk=close-stop
            target=close+rr*risk
        # Spread + two modeled slips must be <= 20% stop distance.
        if not match or not isfinite(risk) or risk<=0 or cost>.20*risk:
            continue
        candidates.append({**wait,"research_side":side,
            "reason":"3 potwierdzone pivoty 2+2; breakout; EMA21; ATR; koszt",
            "signal_mid":round(close,5),"stop_mid":round(stop,5),
            "target_mid":round(target,5),"risk_mid_pts":round(risk,5),
            "rr_gross":rr,"atr14":round(atr,5),
            "spread_model":round(spr,5),"slippage_side":slippage,
            "cost_source":spr_source,
            "pivot1_utc":frame.index[p1].isoformat(),
            "pivot2_utc":frame.index[p2].isoformat(),
            "pivot3_utc":frame.index[p3].isoformat(),
            "break_level":round(level,5),"signal_index":i})
    return candidates[0] if len(candidates)==1 else {
        **wait,"reason":"KONFLIKT 3F" if candidates else wait["reason"]}


def current_3f_research(frame,*,spread=2.,slippage=.25,rr=1.8):
    """Inspect last CLOSED M15 only, without generating PAPER orders."""
    _validate(frame,spread,slippage,rr)
    i=len(frame)-1
    for chunk in _chunks(frame):
        if chunk[-1]==i:
            return _signal(frame,indicators(frame),i,chunk[0],
                           spread=spread,slippage=slippage,rr=rr)
    return {"strategy":NAME,"research_side":"WAIT",
            "trade_permission":"WAIT","version":VERSION,
            "signal_utc":frame.index[-1].isoformat(),
            "reason":"POZA REGULARNĄ SESJĄ NY M15"}


def _simulate(frame,setup,*,fallback_spread,slippage,max_holding=MAX_HOLD):
    """Next CLOSED-bar open model, SL-first, session-bound, never fills gaps."""
    i=int(setup["signal_index"]);side=setup["research_side"]
    stop=float(setup["stop_mid"]);target=float(setup["target_mid"])
    if i+1>=len(frame):
        return {"status":"PENDING_NEXT_BAR","pnl_pts":None}
    entry_time=frame.index[i+1]
    if (entry_time-frame.index[i]!=pd.Timedelta(minutes=15)
            or _nyday(entry_time)!=_nyday(frame.index[i])
            or not _cash(entry_time)):
        return {"status":"INVALIDATED_NO_NEXT_BAR","pnl_pts":None}
    mid=float(frame.Open.iloc[i+1])
    if not (stop<mid<target if side=="LONG" else target<mid<stop):
        return {"status":"INVALIDATED_ENTRY_GAP","pnl_pts":None}
    half=float(setup["spread_model"])/2
    filled=mid+half+slippage if side=="LONG" else mid-half-slippage
    base={"entry_utc":entry_time.isoformat(),"entry_mid":round(mid,5),
          "entry_executable":round(filled,5),
          "execution":"RETROSPECTIVE_NEXT_CLOSED_BAR_OPEN_MODEL"}
    for j in range(i+1,min(len(frame),i+max_holding+1)):
        stamp=frame.index[j]
        if ((j>i+1 and stamp-frame.index[j-1]!=pd.Timedelta(minutes=15))
                or _nyday(stamp)!=_nyday(frame.index[i]) or not _cash(stamp)):
            return {**base,"status":"INVALIDATED_GAP","pnl_pts":None}
        row=frame.iloc[j];half_out=_spread(frame,j-1,fallback_spread)[0]/2
        status=None
        if side=="LONG":
            if row.Low<=stop:
                exit_mid=min(stop,float(row.Open));status="SL"
            elif row.High>=target:
                exit_mid=target;status="TP"
        else:
            if row.High>=stop:
                exit_mid=max(stop,float(row.Open));status="SL"
            elif row.Low<=target:
                exit_mid=target;status="TP"
        session_end=stamp.tz_convert(NY).time()==LAST
        if status is None and not (j-i>=max_holding or session_end):
            continue
        if status is None:
            exit_mid=float(row.Close)
            status="SESSION_TIMEOUT" if session_end else "TIMEOUT"
        exit_exec=(exit_mid-half_out-slippage if side=="LONG"
                   else exit_mid+half_out+slippage)
        pnl=exit_exec-filled if side=="LONG" else filled-exit_exec
        return {**base,"exit_utc":stamp.isoformat(),"exit_mid":round(exit_mid,5),
                "exit_executable":round(exit_exec,5),"status":status,
                "pnl_pts":round(pnl,4),"r_net":round(pnl/setup["risk_mid_pts"],4),
                "bars_held":j-i}
    return {**base,"status":"PENDING_FUTURE_BARS","pnl_pts":None}


def run_3f_replay(frame,*,spread=2.,slippage=.25,rr=1.8,
                  max_holding=MAX_HOLD,split=.70):
    """Exploratory replay. Only the FIRST valid 3F signal per NY session."""
    _validate(frame,spread,slippage,rr)
    if max_holding!=MAX_HOLD or not .5<=split<=.85:
        raise ValueError("3F: invalid holding period or split")
    features=indicators(frame)
    split_utc=frame.index[int(len(frame)*split)]
    used=set();records=[]
    for chunk in _chunks(frame):
        for i in chunk:
            day=_nyday(frame.index[i])
            if day in used:break
            setup=_signal(frame,features,i,chunk[0],
                          spread=spread,slippage=slippage,rr=rr)
            if setup["research_side"] not in ("LONG","SHORT"):
                continue
            used.add(day)
            result=_simulate(frame,setup,fallback_spread=spread,
                             slippage=slippage,max_holding=max_holding)
            final=result.get("exit_utc") or result.get("entry_utc")
            if (final and pd.Timestamp(setup["signal_utc"])<split_utc
                    <=pd.Timestamp(final)):
                result={"status":"SPLIT_EMBARGO","pnl_pts":None}
            setup.pop("signal_index")
            records.append({**setup,**result,"sample":(
                "EARLIER_70" if frame.index[i]<split_utc else "LATER_30")})
    return pd.DataFrame(records)


def research_scorecard(rows):
    """No data != zero PnL; no validation/auto-entry claim."""
    if isinstance(rows,pd.DataFrame):rows=rows.to_dict("records")
    rows=list(rows or [])
    out=[]
    for side in ("LONG","SHORT"):
        all_rows=[r for r in rows if r.get("research_side")==side]
        pnls=[float(r["pnl_pts"]) for r in all_rows
              if r.get("status") in RESOLVED and r.get("pnl_pts") is not None]
        wins=sum(v>0 for v in pnls);loss=-sum(v for v in pnls if v<0)
        out.append({"side":side,"signals":len(all_rows),
            "closed":len(pnls),"net_pts":round(sum(pnls),2) if pnls else None,
            "expectancy_pts":round(sum(pnls)/len(pnls),3) if pnls else None,
            "win_rate_pct":round(100*wins/len(pnls),1) if pnls else None,
            "profit_factor":round(sum(v for v in pnls if v>0)/loss,3)
                if len(pnls)>=30 and loss else None,
            "pending":sum(str(r.get("status","")).startswith("PENDING")
                          for r in all_rows),
            "invalidated":sum(str(r.get("status","")).startswith(
                ("INVALIDATED","SPLIT_EMBARGO")) for r in all_rows),
            "status":"BADANIE; BRAK NIEZALEŻNEGO OOS",
            "trade_permission":"WAIT"})
    return out
