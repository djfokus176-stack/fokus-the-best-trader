"""Explicit owner-triggered FORWARD ONLY virtual US500 trial, independent of AUTO.

The browser sends NO broker orders: it writes one CAS-protected intent to
the SAME Supabase checkpoint. Only the Northflank worker evaluates upcoming,
verified, consecutive closed M1 candles. No historical replay, no artificial
market data, no bypass of market/data/global protections. A manual test is
not a strategy signal and cannot contaminate AUTO/RAW/MOMENTUM performance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from uuid import uuid4
import pandas as pd

from .momentum_paper_test import (
    SOURCE, SLIPPAGE, _valid_frame, _time, _finite,
)
from .strategy import indicators
from .remote_checkpoint import RemoteConflict

SCHEMA=1
REQUEST_TTL_MINUTES=15
MAX_REQUESTS_UTC_DAY=3
MAX_HOLD_M1=5
MAX_HISTORY=80


def blank():
    return {
        "schema":SCHEMA,"request":None,"active":None,
        "closed":[],"invalidated_rows":[],
        "last_candle_utc":None,"last_reason":"JESZCZE_NIE_TESTOWANO",
        "attempted_days":{},"requested_count":0,"opened":0,
        "closed_total":0,"invalidated_total":0,
    }


def _now_utc(value=None):
    current=_time(value) if value is not None else pd.Timestamp.now(tz="UTC")
    if current is None:
        raise ValueError("Wymagany poprawny czas UTC")
    return current


def _existing(value):
    return value if isinstance(value,dict) and value.get("schema")==SCHEMA else blank()


def _unresolved(state):
    req=state.get("request")
    active=state.get("active")
    return bool(isinstance(req,dict) and req.get("status") in
                ("QUEUED","WAIT_DATA")) or bool(
                isinstance(active,dict) and active.get("status") in
                ("PENDING","OPEN"))


def queue_manual_request(remote,side,*,now=None):
    """Owner-only UI endpoint. Exactly one requested side, 3 UTC/day.

    UI must run *inside* the existing owner-authenticated Streamlit terminal.
    CAS retries only the payload modification, NOT any broker order.
    """
    if side not in ("LONG","SHORT"):
        raise ValueError("Niedozwolony kierunek: tylko LONG / SHORT")
    current=_now_utc(now)
    for _ in range(3):
        version,payload=remote.fetch()
        if not isinstance(payload,dict) or payload.get("schema")!=1:
            raise ValueError("Nieprawidłowy checkpoint Supabase")
        meta=payload.get("meta") or {}
        if (meta.get("source")!=SOURCE or meta.get("epic")!="US500"
                or meta.get("strategy")!="AUTO — 6 STRATEGII"
                or meta.get("timeframe")!="MINUTE"):
            return {"status":"WRONG_WORKER_MODE"}
        # A dead worker must not accept a request as though it were LIVE.
        last=_time(meta.get("last_scan_utc"))
        if last is None or not 0<=(current-last).total_seconds()<=300:
            return {"status":"WORKER_NOT_FRESH"}
        data={**_existing(payload.get("manual_paper_test"))}
        if _unresolved(data):
            return {"status":"TEST_ALREADY_QUEUED_OR_ACTIVE",
                    "side":side}
        day=current.strftime("%Y-%m-%d")
        counts=dict(data.get("attempted_days") or {})
        if int(counts.get(day,0))>=MAX_REQUESTS_UTC_DAY:
            return {"status":"MANUAL_TEST_DAILY_LIMIT_3"}
        # Avoid sending a new request immediately after a test finishes:
        # explicit intentional click rather than a tight repeat loop.
        recent=_time(data.get("last_request_utc"))
        if recent is not None and 0<=(current-recent).total_seconds()<120:
            return {"status":"MANUAL_TEST_COOLDOWN_2_MIN"}
        request={"id":uuid4().hex,"side":side,
                 "requested_utc":current.isoformat(),
                 "status":"QUEUED","waiting_reason":"WAIT_NEXT_VERIFIED_M1"}
        counts={k:v for k,v in counts.items()
                if k>=str((current-pd.Timedelta(days=2)).date())}
        counts[day]=int(counts.get(day,0))+1
        data["request"]=request
        data["attempted_days"]=counts
        data["requested_count"]=int(data.get("requested_count",0))+1
        data["last_request_utc"]=current.isoformat()
        data["last_reason"]="QUEUED_"+side
        payload["manual_paper_test"]=data
        payload["manual_paper_test_report"]=manual_report(data)
        try:
            remote.save(version,payload)
        except RemoteConflict:
            # Worker won CAS; refetch fresh values rather than replacing
            # newer PAPER results or creating two requests.
            continue
        return {"status":"QUEUED","side":side,"id":request["id"]}
    return {"status":"CONCURRENT_UPDATE_RETRY"}


def _invalidate(data,position,stamp,reason):
    item={**position,
          "status":"INVALIDATED",
          "previous_status":position.get("status"),
          "invalidated_utc":stamp.isoformat(),
          "invalidation_reason":reason,
          "exit_mid":None,"pnl_pts":None,"closed_utc":None}
    data["invalidated_rows"]=(list(data.get("invalidated_rows") or [])+
                              [item])[-MAX_HISTORY:]
    data["invalidated_total"]=int(data.get("invalidated_total",0))+1
    data["active"]=None
    data["last_reason"]="INVALIDATED_"+reason


def _progress(data,candle,stamp):
    pos=dict(data["active"])
    try:
        op,hi,lo,cl=(
            float(candle.Open),float(candle.High),
            float(candle.Low),float(candle.Close))
    except (TypeError,ValueError,OverflowError,AttributeError):
        _invalidate(data,pos,stamp,"INVALID_CANDLE")
        return
    if not (all(isfinite(v) for v in (op,hi,lo,cl)) and
            lo<=min(op,cl)<=max(op,cl)<=hi):
        _invalidate(data,pos,stamp,"INVALID_CANDLE")
        return
    side=pos["side"]
    if pos["status"]=="PENDING":
        if _time(pos["setup_utc"])+pd.Timedelta(minutes=1)!=stamp:
            _invalidate(data,pos,stamp,"MISSING_NEXT_M1_FILL")
            return
        if not (pos["stop"]<op<pos["target"] if side=="LONG"
                else pos["target"]<op<pos["stop"]):
            _invalidate(data,pos,stamp,"GAP_OUTSIDE_SL_TP")
            return
        cost=pos["spread"]/2+SLIPPAGE
        pos.update(status="OPEN",entry_mid=op,
                   entry_exec=op+(cost if side=="LONG" else -cost),
                   entry_bar_open_utc=(stamp-pd.Timedelta(minutes=1)).isoformat(),
                   opened_utc=stamp.isoformat(),bars_held=0)
        data["opened"]=int(data.get("opened",0))+1
    pos["bars_held"]+=1
    if side=="LONG":
        hit_sl=lo<=pos["stop"]
        hit_tp=hi>=pos["target"]
    else:
        hit_sl=hi>=pos["stop"]
        hit_tp=lo<=pos["target"]
    if hit_sl:
        result="CLOSED_SL"
        at=min(op,pos["stop"]) if side=="LONG" else max(op,pos["stop"])
    elif hit_tp:
        result="CLOSED_TP"
        at=pos["target"]
    elif pos["bars_held"]>=MAX_HOLD_M1:
        result="CLOSED_TIMEOUT"
        at=cl
    else:
        data["active"]=pos
        data["last_reason"]="OPEN_"+side
        return
    fee=pos["spread"]/2+SLIPPAGE
    exit_exec=at-fee if side=="LONG" else at+fee
    net=(exit_exec-pos["entry_exec"] if side=="LONG"
         else pos["entry_exec"]-exit_exec)
    if not isfinite(net):
        _invalidate(data,pos,stamp,"INVALID_NET_RESULT")
        return
    pos.update(status=result,closed_utc=stamp.isoformat(),
               exit_mid=round(at,4),exit_exec=round(exit_exec,4),
               pnl_pts=round(net,3))
    data["closed"]=(list(data.get("closed") or [])+[pos])[-MAX_HISTORY:]
    data["closed_total"]=int(data.get("closed_total",0))+1
    data["active"]=None
    data["last_reason"]=result


def expire_request_only(state,*,now=None):
    """Expiry still applies if broker scan returned BEFORE M1 reviewer."""
    data={**_existing(state)}
    request=data.get("request")
    if isinstance(request,dict) and request.get("status") in ("QUEUED","WAIT_DATA"):
        created=_time(request.get("requested_utc"))
        current=_now_utc(now)
        if created is None or (current-created).total_seconds()>REQUEST_TTL_MINUTES*60:
            data["request"]={**request,"status":"EXPIRED",
                             "waiting_reason":"EXPIRED_NO_VALID_M1"}
            data["last_reason"]="EXPIRED_NO_VALID_M1"
    return data


def advance_manual_test(state,frame,blockers=(),*,spread,source=SOURCE,
                        epic="US500",market_status="TRADEABLE",now=None):
    """Advance only on next fresh verified closed M1 of DEMO US500.

    This deliberately disregards *directional strategy* when owner triggers,
    but never overrides genuine global worker gates, data validity,
    current broker status, or source environment.
    """
    current=_now_utc(now)
    data=expire_request_only(state,now=current)
    request=data.get("request")
    if (source!=SOURCE or epic!="US500" or market_status!="TRADEABLE"):
        data["last_reason"]="WAIT_MARKET_DEMO_TRA..."+
                           "DEABLE" if market_status!="TRADEABLE" else "WAIT_DEMO_SOURCE"
        return data
    if not _valid_frame(frame):
        data["last_reason"]="WAIT_VERIFIED_M1"
        return data
    cost=_finite(spread)
    if cost is None or cost<0:
        data["last_reason"]="WAIT_VALID_SPREAD"
        return data
    stamp=frame.index[-1].tz_convert("UTC")
    last=_time(data.get("last_candle_utc"))
    if last is not None and stamp<=last:
        return data
    # No stale / future frame becomes a "current" synthetic position.
    if not 0<=(current-stamp).total_seconds()<=155:
        data["last_reason"]="WAIT_FRESH_M1_CLOSE"
        return data
    data["last_candle_utc"]=stamp.isoformat()
    active=data.get("active")
    if isinstance(active,dict) and active.get("status") in ("PENDING","OPEN"):
        if last is not None and stamp-last!=pd.Timedelta(minutes=1):
            _invalidate(data,active,stamp,"MISSING_CANDLE_GAP")
            return data
        _progress(data,frame.iloc[-1],stamp)
        return data
    if not isinstance(request,dict) or request.get("status") not in ("QUEUED","WAIT_DATA"):
        return data
    created=_time(request.get("requested_utc"))
    if created is None or stamp<=created:
        request={**request,"status":"WAIT_DATA",
                 "waiting_reason":"WAIT_FUTURE_M1_CLOSE"}
        data["request"]=request
        data["last_reason"]="WAIT_NEXT_M1_AFTER_CLICK"
        return data
    if blockers:
        data["request"]={**request,"status":"WAIT_DATA",
                         "waiting_reason":"WORKER_GATES_"+",".join(str(b) for b in blockers)[:90]}
        data["last_reason"]="WAIT_WORKER_GLOBAL_GATES"
        return data
    row=indicators(frame).iloc[-1]
    atr=_finite(row.ATR)
    signal=_finite(row.Close)
    if atr is None or atr<=0 or signal is None or signal<=0:
        data["last_reason"]="WAIT_ATR_AND_CLOSE"
        return data
    if cost>max(1.2,.65*atr):
        data["last_reason"]="WAIT_SPREAD_TOO_HIGH"
        return data
    risk=max(2.0,1.3*atr,2.0*cost)
    reward=max(2.5,1.65*atr)
    side=request["side"]
    if side=="LONG":
        sl=signal-risk
        tp=signal+reward
    else:
        sl=signal+risk
        tp=signal-reward
    if not (isfinite(sl) and isfinite(tp) and sl>0 and tp>0):
        data["last_reason"]="WAIT_GEOMETRY"
        return data
    data["active"]={
        "status":"PENDING","side":side,
        "strategy":"MANUAL PAPER TEST 5M",
        "methods":["TEST RĘCZNY "+side],"request_id":request["id"],
        "setup_utc":stamp.isoformat(),
        "entry_signal":round(signal,4),"stop":round(sl,4),
        "target":round(tp,4),"spread":round(cost,4),
        "bars_held":0,
    }
    data["request"]={**request,"status":"ACCEPTED",
                     "waiting_reason":"PENDING_NEXT_M1_OPEN"}
    data["last_reason"]="PENDING_NEXT_VERIFIED_M1"
    return data


def manual_report(state):
    data=_existing(state)
    active=data.get("active") if isinstance(data.get("active"),dict) else None
    closed=[p for p in (data.get("closed") or [])
            if isinstance(p,dict) and p.get("status") in
            ("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")]
    return {
        "status":"OWNER_MANUAL_PAPER_ONLY",
        "request":data.get("request"),
        "active":active,
        "closed":len(closed),
        "opened":int(data.get("opened",0)),
        "requested":int(data.get("requested_count",0)),
        "pnl_pts":round(sum(float(p.get("pnl_pts") or 0)
                             for p in closed),2),
        "last_candle_utc":data.get("last_candle_utc"),
        "last_reason":data.get("last_reason"),
        "recent":list(reversed(closed[-30:])),
        "invalidated_recent":list(reversed((data.get("invalidated_rows") or [])[-30:])),
        "no_broker_orders":True,
        "max_hold_bars":MAX_HOLD_M1,
    }
