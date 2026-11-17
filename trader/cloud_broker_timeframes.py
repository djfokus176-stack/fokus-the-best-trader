"""Read-only, provider-sourced unfinished M5 and H1 for CLOUD chart.

This intentionally does NOT create candles from a two-minute quote cache or
promote unfinished data into AUTO, PAPER, MTF verification, checkpoints or
historical OHLC. All prices are real OHLC from Capital.com DEMO /prices.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

import pandas as pd

SOURCE = "Capital.com /prices • bieżąca OHLC"
QUOTE_SOURCE = "Capital.com DEMO REST"
CONFIG = {
    "M5": ("MINUTE_5", 300, "forming_m5", "BROKER_INCOMPLETE_M5"),
    "H1": ("HOUR", 3600, "forming_h1", "BROKER_INCOMPLETE_H1"),
}
MAX_PREVIEW_AGE_SECONDS = 48


def _utc(value):
    at = pd.Timestamp(value)
    if pd.isna(at) or at.tzinfo is None:
        raise ValueError("CLOUD MTF requires timezone-aware UTC timestamps")
    return at.tz_convert("UTC")


def serialize_broker_forming(snapshot, choice, *, now=None):
    """Validate OHLC and exact current bar boundaries, never older candles."""
    if choice not in CONFIG:
        raise ValueError("Unsupported provider forming timeframe")
    resolution, seconds, _, kind = CONFIG[choice]
    if (not isinstance(snapshot, dict)
            or snapshot.get("source") != SOURCE
            or snapshot.get("epic") != "US500"
            or snapshot.get("environment") != "DEMO"
            or snapshot.get("timeframe") != resolution):
        raise ValueError("Untrusted provider forming data")
    at = _utc(now if now is not None else datetime.now(timezone.utc))
    opened = _utc(snapshot["last_tick"])
    closed = _utc(snapshot["time"])
    if (closed - opened != pd.Timedelta(seconds=seconds)
            or opened != at.floor(f"{seconds}s")
            or not opened <= at < closed):
        raise ValueError("Not the current unfinished provider candle")
    o, h, l, c = (float(snapshot[k]) for k in
                  ("Open", "High", "Low", "Close"))
    bid, ask, spread = (float(snapshot[k]) for k in
                        ("bid", "ask", "spread"))
    if (not all(isfinite(x) for x in (o,h,l,c,bid,ask,spread))
            or min(o,h,l,c,bid) <= 0 or ask < bid or spread < 0
            or abs(ask-bid-spread) > .002 or
            h < max(o,l,c) or l > min(o,h,c)):
        raise ValueError("Invalid provider OHLC or spread")
    return {
        "kind":kind,"epic":"US500","environment":"DEMO",
        "timeframe":resolution,"source":SOURCE,
        "bar_open_utc":opened.isoformat(),
        "bar_close_utc":closed.isoformat(),
        "collected_utc":at.isoformat(),
        "open":o,"high":h,"low":l,"close":c,
        "bid":bid,"ask":ask,"spread":spread,
    }


def assess_broker_forming(record,choice,*,now=None,last_closed_utc=None):
    """Display-only current OHLC; no direct broker calls or trade permission."""
    missing = {"visible":False,"reason":"BRAK_SWIEZEJ_OHLC_BROKERA",
               "bar":None,"quote_verified":False,
               "trade_permission":"WAIT","missing_extremes_possible":True}
    if choice not in CONFIG:
        raise ValueError("Unsupported provider forming timeframe")
    if (not isinstance(record,dict) or record.get("source")!=QUOTE_SOURCE
            or record.get("epic")!="US500"
            or record.get("broker_status")!="TRADEABLE"):
        return missing
    _,secs,key,kind=CONFIG[choice]
    data=record.get("samples")
    if not isinstance(data,list) or not data or not isinstance(data[-1],dict):
        return missing
    last=data[-1]
    try:
        from .cloud_scalp_5s_ui import assess_quote_snapshot
        at=_utc(now if now is not None else datetime.now(timezone.utc))
        fresh=bool(assess_quote_snapshot(record,now=at)["fresh"])
    except (TypeError,ValueError,KeyError,OverflowError):
        return {**missing,"reason":"NIEPOPRAWNY_CZAS_LUB_QUOTE"}
    if not fresh:
        # Only a current broker /prices result, explicitly marked
        # unverified by the single Northflank collector, may be displayed.
        # It is NEVER a validated broker quote or a trading price.
        try:
            fallback=(last.get("fallback_only") is True and
                      last.get("source_delay_unknown") is True and
                      float(record.get("delay_seconds"))==9999.)
        except (TypeError,ValueError,OverflowError):
            fallback=False
        if not fallback:
            return {**missing,"reason":"QUOTE_NIEPOTWIERDZONY"}
    raw=last.get(key)
    if (not isinstance(raw,dict) or raw.get("kind")!=kind or
            raw.get("source")!=SOURCE or
            raw.get("environment")!="DEMO" or
            raw.get("epic")!="US500" or
            raw.get("timeframe")!=CONFIG[choice][0]):
        return missing
    try:
        opened=_utc(raw["bar_open_utc"])
        close=_utc(raw["bar_close_utc"])
        collected=_utc(raw["collected_utc"])
        age=(at-collected).total_seconds()
        if (close-opened != pd.Timedelta(seconds=secs)
                or opened!=at.floor(f"{secs}s")
                or not 0 <= age <= MAX_PREVIEW_AGE_SECONDS
                or not opened <= at < close):
            return {**missing,"reason":"NIEAKTUALNA_OHLC_BROKERA"}
        if last_closed_utc is not None and close <= _utc(last_closed_utc):
            return {**missing,"reason":"JUZ_ZAMKNIETA_SWI_ECA"}
        o,h,l,c=(float(raw[k]) for k in ("open","high","low","close"))
        bid,ask,spread=(float(raw[k]) for k in ("bid","ask","spread"))
        if (not all(isfinite(x) for x in (o,h,l,c,bid,ask,spread))
                or min(o,h,l,c,bid)<=0 or ask<bid or spread<0
                or abs(ask-bid-spread)>.002 or
                h<max(o,l,c) or l>min(o,h,c)):
            return {**missing,"reason":"NIEPOPRAWNA_OHLC"}
    except (KeyError,TypeError,ValueError,OverflowError):
        return {**missing,"reason":"NIEPOPRAWNA_OHLC"}
    return {"visible":True,
            "reason":("NIEUKONCZONA_OHLC_BROKERA" if fresh
                      else "OHLC_BROKERA_QUOTE_NIEZWERYFIKOWANY"),
            "bar":{**raw,"at":close,
                   "capture_age_seconds":round(age,1),
                   "first_vendor_utc":opened.isoformat()},
            "quote_verified":fresh,
            "missing_extremes_possible":False,
            "broker_m1_only":False,
            "trade_permission":"WAIT","incomplete":True}
