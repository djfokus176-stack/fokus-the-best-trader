"""Honest moving M15 WICKS from observed Capital.com DEMO quotes.

NEVER use this provisional display candle as confirmed OHLC, training,
signals, SL/TP, PAPER, broker fills, or strategy selection.

Two independent, explicitly labeled representations:
* SAMPLED_M15_MID: Open = first observed REST MID in THIS 15-minute
  interval, High/Low = observed extrema (not unseen market extremes),
  Close = latest observed MID. Moves when fresh BID/ASK changes.
* BROKER_INCOMPLETE_M15: optional actual /prices M15 OHLC from the same
  Northflank read-only broker session, subject to time/freshness checks.

No fake ticks, no interpolation, no stale bar masquerading as LIVE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import pandas as pd

FROM_PRICES="Capital.com /prices • bieżąca OHLC"
QUOTE_SOURCE="Capital.com DEMO REST"
BROKER_KIND="BROKER_INCOMPLETE_M15"
SAMPLED_KIND="SAMPLED_M15_MID"
MAX_SAMPLE_AGE=12.0
MAX_BROKER_AGE=35.0


def _utc(value):
    stamp=pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("M15 requires tz-aware timestamp")
    return stamp.tz_convert("UTC")


def _bounds(utc):
    timestamp=_utc(utc)
    start=timestamp.floor("15min")
    return start,start+pd.Timedelta(minutes=15)


def _valid_ohlc(o,h,l,c):
    return (all(isfinite(v) and v>0 for v in (o,h,l,c))
            and h>=max(o,l,c) and l<=min(o,h,c))


def broker_forming_m15(snapshot,*,now=None):
    """Validate broker OHLC from an as-of OPEN-labelled, UNFINISHED M15."""
    if (not isinstance(snapshot,dict)
            or snapshot.get("epic")!="US500"
            or snapshot.get("environment")!="DEMO"
            or snapshot.get("timeframe")!="MINUTE_15"
            or snapshot.get("source")!=FROM_PRICES):
        raise ValueError("Untrusted M15 /prices source")
    at=_utc(now or datetime.now(timezone.utc))
    opened=_utc(snapshot["last_tick"])
    closed=_utc(snapshot["time"])
    if closed-opened!=pd.Timedelta(minutes=15):
        raise ValueError("M15 broker period mismatch")
    # A stale previous quarter can NEVER be re-labeled as current.
    if _bounds(at)!=(opened,closed):
        raise ValueError("M15 broker candle is not the current open bar")
    o,h,l,c=(float(snapshot[k]) for k in ("Open","High","Low","Close"))
    bid,ask,spread=(float(snapshot[k]) for k in ("bid","ask","spread"))
    if (not _valid_ohlc(o,h,l,c) or not all(isfinite(v) for v in
            (bid,ask,spread)) or bid<=0 or ask<bid or spread<0
            or abs(ask-bid-spread)>.002):
        raise ValueError("Invalid M15 broker OHLC/BID-ASK")
    return {"kind":BROKER_KIND,"epic":"US500","environment":"DEMO",
            "timeframe":"MINUTE_15","source":FROM_PRICES,
            "bar_open_utc":opened.isoformat(),"bar_close_utc":closed.isoformat(),
            "collected_utc":at.isoformat(),"open":o,"high":h,"low":l,
            "close":c,"bid":bid,"ask":ask,"spread":spread}


def update_sampled_m15(previous, quote):
    """Extend one provisional M15 bar ONLY from a fresh vendor quote.

    Quote.update_utc identifies the actual vendor observation. Repeated
    vendor timestamps are ignored (no fabricated movement or sample count).
    Sampling may begin after the quarter started, and can miss true H/L.
    """
    if (getattr(quote,"epic",None)!="US500"
            or getattr(quote,"environment",None)!="DEMO"
            or getattr(quote,"status",None)!="TRADEABLE"
            or getattr(quote,"fresh",None) is not True
            or getattr(quote,"update_utc",None) is None):
        return None
    received=_utc(quote.received_utc)
    vendor=_utc(quote.update_utc)
    age=(received-vendor).total_seconds()
    if not -2<=age<=30:
        return None
    o,c=(float(quote.mid),float(quote.mid))
    if not all(isfinite(v) and v>0 for v in (o,c)):
        return None
    start,end=_bounds(vendor)
    if not start<=received<end:
        return None
    same=isinstance(previous,dict) and previous.get("kind")==SAMPLED_KIND
    if same:
        try:
            same=(_utc(previous["bar_open_utc"])==start
                  and _utc(previous["last_vendor_utc"])<vendor
                  and _utc(previous["first_vendor_utc"])<=vendor)
        except (ValueError,TypeError,KeyError):
            same=False
    if same:
        opening=float(previous["open"])
        high=max(float(previous["high"]),c)
        low=min(float(previous["low"]),c)
        n=int(previous["samples"])+1
        first=previous["first_vendor_utc"]
    else:
        # duplicate timestamp of same period => DO NOT count fake ticks
        if isinstance(previous,dict) and previous.get("kind")==SAMPLED_KIND:
            try:
                if (_utc(previous["bar_open_utc"])==start and
                        vendor<=_utc(previous["last_vendor_utc"])):
                    return previous
            except (TypeError,ValueError,KeyError):
                pass
        opening=high=low=c
        n=1
        first=vendor.isoformat()
    if not _valid_ohlc(opening,high,low,c):
        return None
    return {"kind":SAMPLED_KIND,"epic":"US500","environment":"DEMO",
            "source":QUOTE_SOURCE,"timeframe":"MINUTE_15",
            "bar_open_utc":start.isoformat(),
            "bar_close_utc":end.isoformat(),
            "first_vendor_utc":first,
            "last_vendor_utc":vendor.isoformat(),
            "collected_utc":received.isoformat(),
            "open":opening,"high":high,"low":low,"close":c,
            "samples":min(n,100000)}


def _parse_candidate(candidate,now,*,kind,source,max_age):
    if (not isinstance(candidate,dict)
            or candidate.get("kind")!=kind
            or candidate.get("epic")!="US500"
            or candidate.get("environment")!="DEMO"
            or candidate.get("source")!=source
            or candidate.get("timeframe")!="MINUTE_15"):
        return None
    try:
        start=_utc(candidate["bar_open_utc"])
        end=_utc(candidate["bar_close_utc"])
        collected=_utc(candidate["collected_utc"])
        if ((start,end)!=_bounds(now) or
                not 0<=(now-collected).total_seconds()<=max_age):
            return None
        o,h,l,c=(float(candidate[k]) for k in
                 ("open","high","low","close"))
        if not _valid_ohlc(o,h,l,c):
            return None
        if kind==SAMPLED_KIND:
            n=int(candidate["samples"])
            first=_utc(candidate["first_vendor_utc"])
            latest=_utc(candidate["last_vendor_utc"])
            if n<1 or not start<=first<=latest<=collected<end:
                return None
        else:
            bid,ask,spread=(float(candidate[k]) for k in
                            ("bid","ask","spread"))
            if (not all(isfinite(v) for v in (bid,ask,spread)) or
                    bid<=0 or ask<bid or spread<0 or
                    abs(ask-bid-spread)>.002):
                return None
        return {**candidate,"at":end,"capture_age_seconds":
                round((now-collected).total_seconds(),1)}
    except (KeyError,ValueError,TypeError,OverflowError):
        return None


def assess_moving_m15(record,*,now=None,last_closed_utc=None):
    """Fail-closed UI adapter; never infer live from old quotes alone."""
    missing={"visible":False,"reason":"BRAK_SWI_EZYCH_M15_LIVE",
             "bar":None,"broker_bar":None,"trade_permission":"WAIT"}
    if not isinstance(record,dict):
        return missing
    from .cloud_scalp_5s_ui import assess_quote_snapshot
    try:
        at=_utc(now if now is not None else datetime.now(timezone.utc))
        q=assess_quote_snapshot(record,now=at)
    except (ValueError,TypeError,OverflowError,KeyError):
        return {**missing,"reason":"NIEWIARYGODNY_QUOTE"}
    verified_quote=bool(q["fresh"])
    samples=record.get("samples")
    if not isinstance(samples,list) or not samples or not isinstance(samples[-1],dict):
        return missing
    last=samples[-1]
    if not verified_quote:
        # Never promote an old quote to LIVE. The ONLY permitted backup
        # is a separately fetched, current /prices bar explicitly tagged
        # fallback_only by the SAME dedicated DEMO Northflank worker.
        # It remains a visual broker snapshot with unverified BID/ASK.
        try:
            admissible=(record.get("source")==QUOTE_SOURCE
                        and record.get("broker_status")=="TRADEABLE"
                        and float(record.get("delay_seconds",1))==0
                        and last.get("fallback_only") is True)
        except (ValueError,TypeError,OverflowError):
            admissible=False
        if not admissible:
            return {**missing,"reason":"QUOTE_NIEAKTUALNY_LUB_RYNEK_ZAMKNIETY"}
    sampled=(_parse_candidate(last.get("sampled_m15"),at,kind=SAMPLED_KIND,
                              source=QUOTE_SOURCE,max_age=MAX_SAMPLE_AGE)
             if verified_quote else None)
    broker=_parse_candidate(last.get("forming_m15"),at,kind=BROKER_KIND,
                            source=FROM_PRICES,max_age=MAX_BROKER_AGE)
    # Never draw a preview whose target closing label is already confirmed.
    if last_closed_utc is not None:
        try:
            closed=_utc(last_closed_utc)
            if sampled is not None and sampled["at"]<=closed:
                sampled=None
            if broker is not None and broker["at"]<=closed:
                broker=None
        except (TypeError,ValueError,OverflowError):
            return missing
    # Prefer continuously updated sampled MID candle; broker official
    # preview remains separately available for sanity/hover comparison.
    visible=sampled or broker
    if visible is None:
        return {**missing,"reason":"WORKER_BRAK_NOWEJ_M15"}
    return {"visible":True,
            "reason":("M15_MID_Z_PRÓBEK" if sampled else
                      "M15_BROKER_BEZ_POTWIERDZONEGO_QUOTE"
                      if not verified_quote else "M15_BROKER_W_TRAKCIE"),
            "bar":visible,"broker_bar":broker,
            "kind":visible["kind"],"quote_verified":verified_quote,
            "trade_permission":"WAIT","incomplete":True,
            "missing_extremes_possible":bool(sampled)}
