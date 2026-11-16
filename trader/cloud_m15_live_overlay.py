"""Read-only mixed-frequency cloud chart safeguards.

M15 bars: closed OHLC from private Supabase table, refresh at most once a
minute. REST BID/ASK samples: independent best-effort observations ~5 s,
NOT exchange ticks, NOT M15 candle updates, NOT broker execution prices.
Never draw a stale/closed/delayed quote as live.
"""
from __future__ import annotations

import pandas as pd

from .cloud_scalp_5s_ui import assess_quote_snapshot


def m15_cache_due(cache, *, now=None, ttl_seconds=60):
    """Pure decision; terminal keeps only per-session browser cache."""
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if pd.isna(now) or now.tzinfo is None:
        raise ValueError("Cloud M15 clock requires timezone")
    now=now.tz_convert("UTC")
    if not isinstance(cache,dict):
        return True
    if any(k not in cache for k in ("url","fetched_utc","frame","payload","version")):
        return True
    try:
        last=pd.Timestamp(cache["fetched_utc"]).tz_convert("UTC")
        secs=(now-last).total_seconds()
    except (TypeError,ValueError,OverflowError):
        return True
    return not (0 <= secs < ttl_seconds)


def cloud_quote_overlay(record, *, now=None):
    """Return only validated current points; never promote stale cache.

    Returns a plain serializable-ish dict with pandas timestamps for Plotly;
    this helper is display-only and never updates Supabase.
    """
    if record is None:
        return {"visible":False,"reason":"Brak zapisu BID/ASK w Supabase.",
                "broker_status":"UNKNOWN","age_seconds":None,"points":[]}
    quote=assess_quote_snapshot(record,now=now)
    if not quote["fresh"]:
        return {"visible":False,
                "reason":"Cena BID/ASK nieaktualna, opóźniona albo rynek zamknięty.",
                "broker_status":quote["broker_status"],
                "age_seconds":quote["age_seconds"],"points":[]}
    received=pd.Timestamp(quote["received_utc"]).tz_convert("UTC")
    points=[]
    unique=set()
    # Only newest 120 seconds of valid original REST samples. Samples never
    # become artificial OHLC bars; late/future/duplicate points are excluded.
    for sample in sorted(quote["samples"],key=lambda x:x["time"]):
        when=sample["time"]
        if (when<received-pd.Timedelta(seconds=120)
                or when>received+pd.Timedelta(seconds=2)
                or when in unique):
            continue
        unique.add(when)
        points.append({"time":when,"mid":float(sample["mid"])})
    if not points or points[-1]["time"]!=received:
        points.append({"time":received,"mid":float(quote["mid"])})
    return {"visible":True,"reason":"Świeża cena REST — M15 bez zmian do zamknięcia.",
            "broker_status":quote["broker_status"],
            "age_seconds":quote["age_seconds"],"points":points,
            "mid":quote["mid"],"bid":quote["bid"],"ask":quote["ask"],
            "spread":quote["spread"],"received_utc":quote["received_utc"],
            "not_tick_data":True,"trade_permission":"WAIT"}


def closed_m15_lag(frame, *, now=None):
    """Descriptive age only; only warn if a separate CURRENT quote is fresh."""
    if frame is None or frame.empty:
        return None
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if pd.isna(now) or now.tzinfo is None:
        raise ValueError("Missing UTC clock")
    last=frame.index[-1]
    return round((now.tz_convert("UTC")-last.tz_convert("UTC")).total_seconds()/60,1)
