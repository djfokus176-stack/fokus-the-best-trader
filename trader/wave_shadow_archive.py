"""WAVE shadow archive: bounded causal M15 observations in existing checkpoint.

Pure research storage, no new database tables, no broker, no effect on AUTO.
Events from the first scan are explicitly BACKFILL, never forward evidence.
After each fresh CLOSED M15, event IDs and conditional excursions are added
idempotently. Missing/cross-session horizons are invalidated, never losses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

from .wave_reversal import detect_waves, VERSION as WAVE_VERSION

SCHEMA="wave_shadow_v1"
MAX_EVENTS=240
HORIZONS=(4,8,16)  # M15 bars: 1, 2 and 4 hours
THRESHOLDS=(.25,.5,1.0)
NY=ZoneInfo("America/New_York")


def _dt(value):
    ts=pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("WAVE: brak strefy czasowej UTC")
    return ts.tz_convert("UTC")


def _score(frame, index_by_time, observation):
    """Resolve ONLY fully observed, contiguous CLOSED M15 future candles."""
    at=_dt(observation["signal_utc"])
    loc=index_by_time.get(at)
    result=dict(observation.get("outcomes") or {})
    if loc is None:
        # This candle rolled off the bounded broker snapshot; do not guess.
        return result
    close=float(observation["signal_close"])
    session=at.tz_convert(NY).date()
    latest=frame.index[-1]
    for bars in HORIZONS:
        for pct in THRESHOLDS:
            key=f"{bars*15}m_{pct:g}pct"
            if key in result:
                continue
            until=at+pd.Timedelta(minutes=15*bars)
            end=loc+bars
            if end>=len(frame):
                if latest>=until:
                    result[key]={"status":"INVALIDATED_MISSING_BARS"}
                continue
            window=frame.iloc[loc+1:end+1]
            expected=pd.date_range(
                start=at+pd.Timedelta(minutes=15),periods=bars,
                freq="15min",tz="UTC")
            if not window.index.equals(expected):
                if latest>=until:
                    result[key]={"status":"INVALIDATED_GAP"}
                continue
            local=window.index.tz_convert(NY)
            if (any(t.date()!=session or t.weekday()>=5
                    or t.hour*60+t.minute>16*60 for t in local)):
                result[key]={"status":"INVALIDATED_SESSION"}
                continue
            up=bool(float(window.High.max())>=close*(1+pct/100.))
            down=bool(float(window.Low.min())<=close*(1-pct/100.))
            result[key]={"status":"CLOSED","up":up,"down":down,
                         "both":bool(up and down),
                         "flat":bool(not up and not down),
                         "resolved_utc":window.index[-1].isoformat()}
    return result


def advance_wave_shadow(state, frame, *, epic="US500",
                        source="Capital.com DEMO REST", cap=MAX_EVENTS):
    """Idempotent archive of latest confirmed M15; no trade PnL or AI signal.

    The full passed frame must consist of CLOSED M15 UTC-labeled bars. In
    production worker this function is called ONLY after owner confirms
    broker timestamps are OPEN and the feed adapter shifts them to CLOSE.
    """
    if source!="Capital.com DEMO REST":
        raise ValueError("WAVE cloud: only read-only Capital DEMO snapshot")
    if not 20<=cap<=MAX_EVENTS:
        raise ValueError("WAVE cloud: bounded event count must be 20..240")
    if frame is None or len(frame)<70 or frame.empty:
        raise ValueError("WAVE cloud: insufficient CLOSED M15")
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("WAVE cloud: timezone required")
    times=frame.index.tz_convert("UTC")
    if times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("WAVE cloud: unsorted or repeated bars")
    if any((t.minute%15) or t.second for t in times):
        raise ValueError("WAVE cloud: expected 15-minute CLOSE UTC timestamps")
    last=times[-1]
    prior=dict(state or {})
    if prior and (prior.get("schema")!=SCHEMA or
                  prior.get("epic")!=epic or prior.get("source")!=source):
        raise ValueError("WAVE cloud: state schema/instrument mismatch")
    old_last=(_dt(prior["last_closed_utc"])
              if prior.get("last_closed_utc") else None)
    if old_last is not None and last<old_last:
        # No rollback: stale broker snapshot cannot erase the archive.
        raise ValueError("WAVE cloud: observed older M15 than checkpoint")
    if old_last is not None and last==old_last:
        return prior
    current=list(prior.get("events") or [])
    known={e.get("event_id") for e in current}
    events=detect_waves(frame)
    for row in events.to_dict("records"):
        at=_dt(row["signal_utc"])
        if at>last or row["event_id"] in known:
            continue
        # On later scans do NOT retroactively insert historical observations
        # from a newly expanded API window into the forward cohort.
        if old_last is not None and at<=old_last:
            continue
        entry={
            "event_id":str(row["event_id"]),
            "strategy_version":str(row["strategy_version"]),
            "signal_utc":at.isoformat(),
            "pivot_utc":_dt(row["pivot_utc"]).isoformat(),
            "side":str(row["direction"]),
            "wave_count":int(row["wave_count"]),
            "pattern":str(row["pattern"]),
            "wave_structure":str(row["wave_structure"]),
            "confirmation":str(row["confirmation"]),
            "regime":str(row["regime"]),
            "signal_close":float(row["signal_close"]),
            "bos_level":float(row["bos_level"]),
            "origin":("BACKFILL" if old_last is None else "FORWARD"),
            "outcomes":{},
        }
        current.append(entry)
        known.add(entry["event_id"])
    # Keep the most recent events, oldest resolved results roll off.
    current=sorted(current,key=lambda e:(e["signal_utc"],e["event_id"]))[-cap:]
    by_time={t:i for i,t in enumerate(times)}
    for record in current:
        record["outcomes"]=_score(frame,by_time,record)
    return {
        "schema":SCHEMA,"epic":epic,"source":source,
        "candle_time_convention":"CLOSE_UTC_CONFIRMED_FROM_OPEN_LABEL",
        "last_closed_utc":last.isoformat(),
        "processed_utc":datetime.now(timezone.utc).isoformat(),
        "events":current,
        "events_retained":len(current),
        "events_forward":sum(e["origin"]=="FORWARD" for e in current),
        "last_event_utc":current[-1]["signal_utc"] if current else None,
        "research_only":True,
        "trading_decision":"UNCHANGED",
        "calibrated_probability":False,
    }


def wave_shadow_scorecard(state):
    """Descriptive counts only; never promote a configuration to AUTO."""
    events=list((state or {}).get("events") or [])
    counts={}
    for e in events:
        for key,result in (e.get("outcomes") or {}).items():
            if result.get("status")!="CLOSED":
                continue
            group=f"{e['origin']}|{e['side']}|{e['wave_count']}|{e['confirmation']}|{key}"
            r=counts.setdefault(group,{"n":0,"up":0,"down":0,"both":0,"flat":0})
            r["n"]+=1
            for k in ("up","down","both","flat"):
                r[k]+=bool(result.get(k))
    return {
        "status":"BADANIE — BRAK KALIBRACJI",
        "last_closed_utc":(state or {}).get("last_closed_utc"),
        "retained_events":len(events),
        "forward_events":sum(e.get("origin")=="FORWARD" for e in events),
        "resolved_conditions":sum(v["n"] for v in counts.values()),
        "groups":counts,
        "trade_permission":"WAIT",
    }
