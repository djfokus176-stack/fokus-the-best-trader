"""Read-only display diagnostics for the US500 CLOUD chart and PAPER ledger.

Separates CLOSED candles, the current quote, PENDING setups and actually
recorded PAPER OPEN/CLOSE rows. A missing plot marker is not a missing trade.
Never creates signals or changes archived positions.
"""
from __future__ import annotations

import pandas as pd

SOURCE="Capital.com DEMO REST"
CLOSED_STATUSES={"CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT"}
OPEN_STATUSES=CLOSED_STATUSES|{"OPEN"}
TF_MINUTES={"M1":1,"M2":2,"M5":5,"M15":15,"H1":60}


def _utc(value):
    try:
        result=pd.Timestamp(value)
        if pd.isna(result) or result.tzinfo is None:
            return None
        return result.tz_convert("UTC")
    except (TypeError,ValueError,OverflowError):
        return None


def cloud_paper_visibility(payload, *, viewport=None):
    """Count VERIFIED v3 position transitions, not hypothetical chart setups.

    All-time counts can exceed plot counts because the graph intentionally
    shows a recent time window. Invalidated/PENDING positions are not OPENs.
    """
    zero={"known":False,"total_open":0,"total_closed":0,
          "active_open":0,"pending":0,"invalidated":0,
          "visible_open":0,"visible_closed":0,
          "last_open_utc":None,"last_close_utc":None,
          "rows":0,"invalid_rows":0}
    if not isinstance(payload,dict) or not isinstance(payload.get("tables"),dict):
        return zero
    meta=payload.get("meta")
    if not isinstance(meta,dict) or meta.get("epic")!="US500" or meta.get("source")!=SOURCE:
        return zero
    all_positions=payload["tables"].get("paper_positions_v3")
    if not isinstance(all_positions,list):
        return zero
    limits=None
    if viewport is not None:
        if not isinstance(viewport,(list,tuple)) or len(viewport)!=2:
            raise ValueError("Bad chart window")
        lo,hi=_utc(viewport[0]),_utc(viewport[1])
        if lo is None or hi is None or lo>hi:
            raise ValueError("Invalid chart UTC window")
        limits=lo,hi
    result={**zero,"known":True}
    for pos in all_positions:
        if (not isinstance(pos,dict) or pos.get("source")!=SOURCE
                or pos.get("epic")!="US500" or pos.get("side") not in ("LONG","SHORT")
                or not isinstance(pos.get("trade_id"),str)):
            result["invalid_rows"]+=1
            continue
        status=pos.get("status")
        if status not in OPEN_STATUSES|{"PENDING","INVALIDATED"}:
            result["invalid_rows"]+=1
            continue
        result["rows"]+=1
        if status=="PENDING":
            result["pending"]+=1
        if status=="OPEN":
            result["active_open"]+=1
        if status=="INVALIDATED":
            result["invalidated"]+=1
        opened=_utc(pos.get("opened_utc"))
        closed=_utc(pos.get("closed_utc"))
        if status in OPEN_STATUSES and opened is not None:
            result["total_open"]+=1
            if not result["last_open_utc"] or opened>result["last_open_utc"]:
                result["last_open_utc"]=opened
            if limits is not None and limits[0]<=opened<=limits[1]:
                result["visible_open"]+=1
        if status in CLOSED_STATUSES and closed is not None:
            result["total_closed"]+=1
            if not result["last_close_utc"] or closed>result["last_close_utc"]:
                result["last_close_utc"]=closed
            if limits is not None and limits[0]<=closed<=limits[1]:
                result["visible_closed"]+=1
    for field in ("last_open_utc","last_close_utc"):
        if result[field] is not None:
            result[field]=result[field].isoformat()
    return result


def cloud_chart_gaps(frame,choice,*,visible_count=35):
    """Describe observed CLOSED candle holes, not a claim of broker outage."""
    if choice not in TF_MINUTES:
        raise ValueError("Unsupported timeframe")
    blank={"known":False,"gaps":0,"missing_slots":0,
           "largest_gap_minutes":0.0,"last_closed_utc":None,
           "bars":0}
    if not isinstance(frame,pd.DataFrame) or frame.empty:
        return blank
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Candle index must be timezone aware")
    idx=frame.index[-max(2,int(visible_count)):].tz_convert("UTC")
    expected=pd.Timedelta(minutes=TF_MINUTES[choice])
    gaps=[]
    for delta in idx.to_series().diff().dropna():
        if delta>expected+pd.Timedelta(seconds=1):
            gaps.append(delta)
    return {"known":True,"gaps":len(gaps),
            "missing_slots":sum(max(0,int(g/expected)-1) for g in gaps),
            "largest_gap_minutes":round(max((g.total_seconds()/60 for g in gaps),default=0),1),
            "last_closed_utc":idx[-1].isoformat(),"bars":len(idx)}
