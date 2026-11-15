"""Autonomous FOKU$ 3F M15 SHADOW archiver, separate from PAPER/AUTO.

First ever seen M15 primes a watermark without replaying old candidates as
fresh FORWARD evidence. One new observed CLOSED M15 may add a new 3F signal.
Existing pending shadow results may progress, but closed outcomes are immutable.
No broker orders, no queue_paper, no automatic new trade permission.
"""
from __future__ import annotations

import pandas as pd

from .fokus_3f import (
    NAME, SOURCE, VERSION, RESOLVED,
    run_3f_replay, research_scorecard,
)
from .wave_reversal import validate_closed_m15

SCHEMA="fokus_3f_forward_v1"
MAX_EVENTS=120
FINISHED=set(RESOLVED)
FINISHED.update(("INVALIDATED_NO_NEXT_BAR","INVALIDATED_ENTRY_GAP",
                 "INVALIDATED_GAP","SPLIT_EMBARGO"))


def _aware(value):
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None or pd.isna(stamp):
        raise ValueError("3F SHADOW: UTC-aware timestamp required")
    return stamp.tz_convert("UTC")


def _whitelist(row):
    keys=("strategy","research_side","trade_permission","version",
          "signal_utc","session_ny","reason","signal_mid","stop_mid",
          "target_mid","risk_mid_pts","rr_gross","atr14",
          "spread_model","slippage_side","cost_source","pivot1_utc",
          "pivot2_utc","pivot3_utc","break_level","entry_utc",
          "entry_mid","entry_executable","execution","exit_utc",
          "exit_mid","exit_executable","bars_held","status","pnl_pts",
          "r_net")
    safe={}
    for key in keys:
        val=row.get(key)
        if val is None:
            continue
        # DataFrame conversion may create NaN/NaT for absent fields on
        # pending records. Supabase checkpoint save uses allow_nan=False:
        # never let one research row break mandatory PAPER accounting.
        try:
            if bool(pd.isna(val)):
                continue
        except (TypeError,ValueError):
            continue
        if hasattr(val,"item"):
            val=val.item()
        if isinstance(val,pd.Timestamp):
            val=val.isoformat()
        safe[key]=val
    return safe


def advance_3f_forward(state,frame,*,epic="US500",source=SOURCE):
    """Persist only newly OBSERVED M15 as FORWARD; never backfill old trades."""
    if epic!="US500" or source!=SOURCE:
        raise ValueError("3F: wrong instrument/source")
    validate_closed_m15(frame)
    last=frame.index[-1].tz_convert("UTC")
    old=dict(state or {})
    if old and old.get("schema")!=SCHEMA:
        raise ValueError("3F: unsupported checkpoint schema")
    previous=_aware(old["last_closed_utc"]) if old.get("last_closed_utc") else None
    if previous is not None and last<previous:
        raise ValueError("3F: cannot rewind forward watermark")
    if previous is not None and last==previous:
        return old
    events=list(old.get("events") or [])
    if len(events)>MAX_EVENTS or any(not isinstance(e,dict) for e in events):
        raise ValueError("3F: corrupt shadow archive")
    stamps=[e.get("signal_utc") for e in events]
    if len(stamps)!=len(set(stamps)):
        raise ValueError("3F: duplicate signal in state")
    if previous is None:
        return {"schema":SCHEMA,"strategy":NAME,"source":source,"epic":epic,
                "version":VERSION,"last_closed_utc":last.isoformat(),
                "status":"PRIMED_NO_HISTORICAL_BACKFILL","events":[],
                "trade_permission":"WAIT","forward_only":True}
    # A discontinuity in observed M15 bars may occur across NY sessions.
    # Require EXACTLY one new closed bar in this incoming snapshot;
    # otherwise never label the missed interval as contemporaneous FORWARD.
    new_bars=frame.index[frame.index>previous]
    contiguous_seen=(len(new_bars)==1 and new_bars[0]==last)
    historical=run_3f_replay(frame)
    by_signal={str(r["signal_utc"]):r for r in historical.to_dict("records")
               } if not historical.empty else {}
    fresh=[]
    for saved in events:
        ident=str(saved["signal_utc"])
        row=by_signal.get(ident)
        if row is None or saved.get("status") in FINISHED:
            fresh.append(saved)
            continue
        # A future candle can finish an already SAVED pending signal.
        if row.get("status") in FINISHED:
            fresh.append({**saved,**_whitelist(row)})
        else:
            fresh.append(saved)
    # New M15 signal must occur AT THE JUST-OBSERVED BAR, not a past bar
    # that arrived in a delayed batch. Existing same-session signal blocks
    # a duplicate even if the earlier one was invalidated.
    if contiguous_seen:
        newest=by_signal.get(last.isoformat())
        if (newest is not None
                and newest.get("research_side") in ("LONG","SHORT")
                and newest.get("session_ny") not in
                {e.get("session_ny") for e in fresh}):
            fresh.append(_whitelist(newest))
    fresh=fresh[-MAX_EVENTS:]
    return {"schema":SCHEMA,"strategy":NAME,"source":source,"epic":epic,
            "version":VERSION,"last_closed_utc":last.isoformat(),
            "status":("FORWARD_3F_SHADOW_ACTIVE" if contiguous_seen
                      else "RECONNECTED_OR_GAPPED_NO_NEW_FORWARD"),
            "events":fresh,"trade_permission":"WAIT","forward_only":True}


def forward_3f_scorecard(state):
    data=state if isinstance(state,dict) else {}
    events=data.get("events") or []
    return {"schema":SCHEMA,
            "status":data.get("status","NOT_YET_PRIMED"),
            "last_closed_utc":data.get("last_closed_utc"),
            "events_forward":len(events),
            "rank":research_scorecard(events),
            "trade_permission":"WAIT",
            "independent_oos_verified":False,
            "model":"M15 next closed-bar simulated entry; no Capital fills"}
