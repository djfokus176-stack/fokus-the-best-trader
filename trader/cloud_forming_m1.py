"""Cloud *incomplete* M1 preview, read-only and entirely separate from PAPER.

The dedicated Northflank worker fetches broker /prices in its EXISTING DEMO
session; private Supabase focus_live_quotes.samples[-1].forming_m1 holds a
small, optional snapshot (no schema change, no second writer/login).

This is a PREVIEW ONLY: never feed it to M1/M15 confirmed candles, AUTO,
SL/TP, PAPER execution, model training, or live trading. No invented bars.
"""
from __future__ import annotations

from datetime import datetime,timezone
from math import isfinite
import pandas as pd

SOURCE="Capital.com /prices • bieżąca OHLC"
TYPE="BROKER_INCOMPLETE_M1"
MAX_RECEIPT_AGE_SECONDS=28


def _utc(value):
    if value is None:
        raise ValueError("Missing preview timestamp")
    stamp=pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("Preview timestamp must be timezone-aware")
    return stamp.tz_convert("UTC")


def serialize_forming_m1(snapshot,*,collected_utc=None):
    """Validate a Capital /prices preview; return JSON-safe, strict data.

    A missing/latest-stale broker M1 is an empty preview, NOT evidence of
    a market freeze. Never shift source candle time twice.
    """
    if not isinstance(snapshot,dict) or snapshot.get("epic")!="US500" or (
            snapshot.get("environment")!="DEMO" or
            snapshot.get("timeframe")!="MINUTE" or snapshot.get("source")!=SOURCE):
        raise ValueError("Unsupported forming M1 source")
    now=_utc(collected_utc if collected_utc is not None else datetime.now(timezone.utc))
    opened=_utc(snapshot.get("last_tick"))
    closed=_utc(snapshot.get("time"))
    if closed-opened!=pd.Timedelta(minutes=1):
        raise ValueError("Unexpected forming M1 time interval")
    if not 0 <= (now-opened).total_seconds() <= 65:
        raise ValueError("Forming M1 from wrong market minute")
    try:
        o,h,l,c=(float(snapshot[name]) for name in ("Open","High","Low","Close"))
        bid,ask,spread=(float(snapshot[name]) for name in ("bid","ask","spread"))
    except (ValueError,KeyError,TypeError,OverflowError):
        raise ValueError("Invalid forming M1 fields") from None
    vals=(o,h,l,c,bid,ask,spread)
    if (not all(isfinite(v) for v in vals) or min(o,h,l,c,bid)<=0
            or ask<bid or spread<0 or abs((ask-bid)-spread)>.002
            or h<max(o,c,l) or l>min(o,c,h)):
        raise ValueError("Corrupt forming M1 prices")
    return {
        "kind":TYPE,"epic":"US500","environment":"DEMO",
        "timeframe":"MINUTE","source":SOURCE,
        "open_utc":opened.isoformat(),"close_utc":closed.isoformat(),
        "collected_utc":now.isoformat(),
        "open":round(o,5),"high":round(h,5),"low":round(l,5),
        "close":round(c,5),"bid":round(bid,5),
        "ask":round(ask,5),"spread":round(spread,5),
    }


def assess_cloud_forming_m1(record,*,now=None):
    """Fail closed on stale/closed/delayed quote or expired vendor M1.

    Returns a canonical preview only when the quoted row itself is fresh
    AND a matching current, recent broker M1 snapshot is attached.
    """
    empty={"visible":False,"reason":"BRAK_SWIEZEJ_M1_W_TRAKCIE",
           "preview":None,"trade_permission":"WAIT"}
    if not isinstance(record,dict):
        return empty
    # The current quote is the authority for whether the market is live:
    # a recent old OHLC JSON in a CLOSED market cannot become LIVE.
    from .cloud_scalp_5s_ui import assess_quote_snapshot
    try:
        quoted=assess_quote_snapshot(record,now=now)
    except (TypeError,KeyError,ValueError,OverflowError):
        return {**empty,"reason":"NIEPOPRAWNY_BID_ASK"}
    if not quoted["fresh"]:
        return {**empty,"reason":"NOT_TRADEABLE_OR_STALE_QUOTE"}
    history=record.get("samples")
    if not isinstance(history,list) or not history:
        return empty
    last=history[-1]
    preview=last.get("forming_m1") if isinstance(last,dict) else None
    if not isinstance(preview,dict):
        return empty
    if (preview.get("kind")!=TYPE or preview.get("source")!=SOURCE
            or preview.get("epic")!="US500" or
            preview.get("environment")!="DEMO" or
            preview.get("timeframe")!="MINUTE"):
        return {**empty,"reason":"NIEZNANE_ZRODLO_M1"}
    try:
        stamp=_utc(now if now is not None else datetime.now(timezone.utc))
        opened=_utc(preview["open_utc"])
        closed=_utc(preview["close_utc"])
        captured=_utc(preview["collected_utc"])
        age=(stamp-captured).total_seconds()
        if (closed-opened!=pd.Timedelta(minutes=1)
                or not 0<=age<=MAX_RECEIPT_AGE_SECONDS
                or not opened<=stamp<closed+pd.Timedelta(seconds=5)):
            return {**empty,"reason":"NIEAKTUALNA_SWI_ECA_M1"}
        o,h,l,c=(float(preview[k]) for k in ("open","high","low","close"))
        bid,ask,spread=(float(preview[k]) for k in ("bid","ask","spread"))
        if (not all(isfinite(x) for x in (o,h,l,c,bid,ask,spread))
                or min(o,h,l,c,bid)<=0 or ask<bid or spread<0
                or abs(ask-bid-spread)>.002
                or h<max(o,l,c) or l>min(o,h,c)):
            return {**empty,"reason":"WADLIWE_OHLC_M1"}
    except (KeyError,TypeError,ValueError,OverflowError):
        return {**empty,"reason":"WADLIWE_OHLC_M1"}
    return {"visible":True,"reason":"BROKER_INCOMPLETE_M1",
            "preview":{**preview,
                       "open_time":opened,"close_time":closed,
                       "captured_time":captured,
                       "age_seconds":round(age,1)},
            "trade_permission":"WAIT","not_closed_candle":True}
