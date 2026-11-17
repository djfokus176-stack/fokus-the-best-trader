"""Independent CLOUD chart intervals; never change AUTO/PAPER timeframe.

M2 does not exist in Capital REST. It is formed ONLY by pairs of
consecutive, source-verified CLOSED M1 candles (CLOSE-labelled UTC).

Provisional current bars are OBSERVATIONS of existing 5s REST samples:
body and wicks may be incomplete; do not use for strategies/backtests.
No extra Capital requests, second broker login, or writes to Supabase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

import pandas as pd

from .cloud_scalp_5s_ui import assess_quote_snapshot

CHART_RESOLUTIONS={
    "M1":("MINUTE",60),
    "M2":("MINUTE",120),
    "M5":("MINUTE_5",300),
    "M15":("MINUTE_15",900),
    "H1":("HOUR",3600),
}


def source_resolution(choice):
    if choice not in CHART_RESOLUTIONS:
        raise ValueError("Unsupported chart-only timeframe")
    return CHART_RESOLUTIONS[choice][0]


def _utc(value):
    stamp=pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("Cloud chart timestamp must be timezone-aware")
    return stamp.tz_convert("UTC")


def closed_chart_frame(raw,choice):
    """Never invent missing M1 bars or include one-minute partial M2.

    Input data is already CLOSED and UTC-indexed as produced by the worker.
    """
    if choice not in CHART_RESOLUTIONS:
        raise ValueError("Unsupported chart-only timeframe")
    if not isinstance(raw,pd.DataFrame) or raw.empty:
        return pd.DataFrame(columns=["Open","High","Low","Close","Spread"],
                            index=pd.DatetimeIndex([],tz="UTC"))
    required=("Open","High","Low","Close","Spread")
    if (not isinstance(raw.index,pd.DatetimeIndex)
            or raw.index.tz is None or raw.index.has_duplicates
            or not raw.index.is_monotonic_increasing
            or not set(required).issubset(raw.columns)):
        raise ValueError("Invalid closed-candle archive")
    if choice!="M2":
        return raw.tail(120).copy()
    # Each M2 is exactly two fully CLOSED, consecutive M1 periods
    # with UTC CLOSE labels (...:01, ...:02) and :02 as M2 CLOSE.
    # Resampling silently drops holes; explicitly check all groups.
    rows=[]
    for end,group in raw.groupby(raw.index.ceil("2min")):
        if len(group)!=2:
            continue
        first,second=group.index
        if second!=end or second-first!=pd.Timedelta(minutes=1):
            continue
        v=group.loc[:,required]
        if v.isna().any().any():
            continue
        o=float(v["Open"].iloc[0])
        h=float(v["High"].max())
        l=float(v["Low"].min())
        c=float(v["Close"].iloc[-1])
        spread=float(v["Spread"].iloc[-1])
        if not (all(isfinite(x) for x in (o,h,l,c,spread))
                and l>0 and spread>=0 and h>=max(o,l,c)
                and l<=min(o,h,c)):
            continue
        rows.append((end,o,h,l,c,spread))
    if not rows:
        return pd.DataFrame(columns=list(required),
                            index=pd.DatetimeIndex([],tz="UTC"))
    result=pd.DataFrame(rows,columns=["Time",*required]).set_index("Time")
    result.index=pd.DatetimeIndex(result.index).tz_convert("UTC")
    return result.tail(120)


def sampled_chart_bar(record,choice,*,now=None,last_closed_utc=None):
    """Display-only OPEN/HIGH/LOW/CLOSE from true recent REST MID samples.

    Never claims to include price action before first observed sample.
    For M5/H1 the 24-sample quote cache may cover just the last ~2 mins.
    """
    empty={"visible":False,"reason":"BRAK_SWIEZYCH_PROBEK",
           "bar":None,"quote_verified":False,
           "trade_permission":"WAIT","missing_extremes_possible":True}
    if choice not in CHART_RESOLUTIONS:
        raise ValueError("Unsupported chart-only timeframe")
    if choice=="M15":
        raise ValueError("M15 uses existing dedicated worker preview")
    if not isinstance(record,dict) or record.get("epic")!="US500":
        return empty
    at=_utc(now if now is not None else datetime.now(timezone.utc))
    samples=record.get("samples")
    if (isinstance(samples,list) and samples and
            isinstance(samples[-1],dict) and
            samples[-1].get("transport")=="CAPITAL_WS_V1"):
        from .cloud_ws_prices import assess_streaming_candle
        return assess_streaming_candle(
            record,choice,now=at,last_closed_utc=last_closed_utc)
    # M5/H1 must use the actual provider /prices OPEN/HIGH/LOW/CLOSE
    # when it is current, not just the last 24 MID samples (~2 min).
    # The read-only worker populated it; no new Capital login here.
    if choice in ("M5","H1"):
        from .cloud_broker_timeframes import assess_broker_forming
        official_tf=assess_broker_forming(
            record,choice,now=at,last_closed_utc=last_closed_utc)
        if official_tf["visible"]:
            return official_tf
    try:
        status=assess_quote_snapshot(record,now=at)
    except (TypeError,KeyError,ValueError,OverflowError):
        return {**empty,"reason":"NIEPOPRAWNY_BID_ASK"}
    # Use the exact currently-forming OHLC from Capital /prices as the
    # old SP500 Master v7.1 did, but fetched ONCE by Northflank rather than
    # logging into Capital from each browser. Strict UTC validation and
    # display-only marker are enforced by assess_cloud_forming_m1.
    from .cloud_forming_m1 import assess_cloud_forming_m1
    official=assess_cloud_forming_m1(record,now=at)
    if official["visible"] and (choice=="M1" or not status["fresh"]):
        m=official["preview"]
        seconds=CHART_RESOLUTIONS[choice][1]
        start=at.floor(f"{seconds}s")
        end=start+pd.Timedelta(seconds=seconds)
        if last_closed_utc is not None:
            try:
                if end<=_utc(last_closed_utc):
                    return {**empty,"reason":"ZAMKNIETA_SWI_ECA_W_ARCHIWUM"}
            except (TypeError,ValueError,OverflowError):
                return {**empty,"reason":"BLEDNY_CZAS_ARCHIWUM"}
        # For M2/M5/H1 this preview covers ONLY the current M1; never
        # claim that its highs/lows span the whole larger interval.
        if _utc(m["open_utc"])>=start and _utc(m["close_utc"])<=end:
            return {"visible":True,
                    "reason":"BROKER_M1_W_TRAKCIE_Z_PRICES",
                    "bar":{
                        "at":end,"open":float(m["open"]),
                        "high":float(m["high"]),"low":float(m["low"]),
                        "close":float(m["close"]),
                        "bar_open_utc":start.isoformat(),
                        "bar_close_utc":end.isoformat(),
                        "collected_utc":m["collected_utc"],
                        "first_vendor_utc":m["open_utc"],
                        "capture_age_seconds":m["age_seconds"],
                        "samples":1,
                    },
                    "quote_verified":official["quote_verified"],
                    "missing_extremes_possible":choice!="M1",
                    "broker_m1_only":choice!="M1",
                    "trade_permission":"WAIT","incomplete":True}
    if not status["fresh"]:
        return {**empty,"reason":"QUOTE_NIEAKTUALNY"}
    seconds=CHART_RESOLUTIONS[choice][1]
    start=at.floor(f"{seconds}s")
    end=start+pd.Timedelta(seconds=seconds)
    if last_closed_utc is not None:
        try:
            if end<=_utc(last_closed_utc):
                return {**empty,"reason":"ZAMKNIETA_SWI_ECA_W_ARCHIWUM"}
        except (TypeError,ValueError,OverflowError):
            return {**empty,"reason":"BLEDNY_CZAS_ARCHIWUM"}
    points={}
    for sample in record.get("samples") or []:
        if not isinstance(sample,dict) or sample.get("fallback_only"):
            continue
        try:
            stamp=_utc(sample["utc"])
            bid=float(sample["bid"]);ask=float(sample["ask"])
            if (not start<=stamp<end or stamp>at+pd.Timedelta(seconds=2)
                    or not all(isfinite(x) for x in (bid,ask))
                    or bid<=0 or ask<bid):
                continue
            points[stamp]=(bid+ask)/2
        except (ValueError,KeyError,TypeError,OverflowError):
            continue
    try:
        last=_utc(record["received_utc"])
        mid=float(status["mid"])
        if (start<=last<end and abs((at-last).total_seconds())<=12
                and isfinite(mid) and mid>0):
            points[last]=mid
    except (ValueError,KeyError,TypeError,OverflowError):
        return empty
    if not points:
        return empty
    ticks=sorted(points.items())
    o=ticks[0][1]
    c=ticks[-1][1]
    h=max(y for _,y in ticks)
    l=min(y for _,y in ticks)
    return {"visible":True,"reason":"MID_Z_AUTENTYCZNYCH_PROBEK",
            "bar":{"at":end,"open":o,"high":h,"low":l,"close":c,
                   "bar_open_utc":start.isoformat(),
                   "bar_close_utc":end.isoformat(),
                   "collected_utc":last.isoformat(),
                   "first_vendor_utc":ticks[0][0].isoformat(),
                   "capture_age_seconds":round((at-last).total_seconds(),1),
                   "samples":len(ticks)},
            "quote_verified":True,
            "missing_extremes_possible":True,
            "trade_permission":"WAIT","incomplete":True}
