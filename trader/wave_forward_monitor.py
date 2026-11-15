"""Read-only WAVE FORWARD audit beside the frozen 2021–2026 A–E study.

FORWARD here means post-first-scan SHADOW events on Capital.com DEMO,
not trades of A/B/C/D strategies. Historical A–E benchmarks come from
Dukascopy; they are shown separately and cannot be pooled, compared as
identical outcomes, or used to calibrate a trading probability.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo
import pandas as pd

from .wave_shadow_archive import HORIZONS, THRESHOLDS
from .wave_fiveyear_report import load_reference_ranking

NY=ZoneInfo("America/New_York")
SIDES=("LONG","SHORT")
CATEGORIES=("up_only","down_only","both","flat")
BENCHMARK_COLS=(
    "FORMACJA","LONG_SHORT","PROBY_OOS","NETTO_OOS",
    "PF_OOS","EXPECTANCY_OOS","STATUS",
)
STATUS="WAIT — BRAK PORÓWNYWALNEGO FORWARD A–E"
MAX_EVENTS=240


def _utc(value):
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("WAVE FORWARD: sygnal nie ma strefy czasu UTC.")
    return stamp.tz_convert("UTC")


def _category(outcome):
    """Exclusive four-way movement category, or None for bad CLOSED data."""
    required=("up","down","both","flat")
    if not isinstance(outcome,dict) or any(
            type(outcome.get(k)) is not bool for k in required):
        return None
    up,down,both,flat=(outcome[k] for k in required)
    if both!=(up and down) or flat!=(not up and not down):
        return None
    if both:
        return "both"
    if up:
        return "up_only"
    if down:
        return "down_only"
    return "flat"


def audit_wave_forward(state, reference=None) -> dict:
    """Calculate observed counts, never a win rate or forecast probability.

    The nine outcomes per event are overlapping conditions. Separating
    UP_ONLY/DOWN_ONLY/BOTH/FLAT is essential to avoid counting BOTH twice.
    Invalidated and pending conditions are never considered losers.
    """
    if not isinstance(state,dict):
        raise ValueError("WAVE FORWARD: brak poprawnego archiwum.")
    if state.get("schema") not in (None,"wave_shadow_v1"):
        raise ValueError("WAVE FORWARD: nieznana wersja archiwum.")
    if state.get("epic") not in (None,"US500"):
        raise ValueError("WAVE FORWARD: archiwum dotyczy innego instrumentu.")
    events=state.get("events") or []
    if not isinstance(events,list) or len(events)>MAX_EVENTS:
        raise ValueError("WAVE FORWARD: niepoprawna liczba zdarzen.")
    seen=set()
    forward=[]
    for e in events:
        if not isinstance(e,dict):
            raise ValueError("WAVE FORWARD: uszkodzone zdarzenie.")
        if e.get("origin")!="FORWARD":
            continue
        uid=e.get("event_id")
        if not isinstance(uid,str) or not uid or uid in seen:
            raise ValueError("WAVE FORWARD: brak lub duplikat ID FORWARD.")
        seen.add(uid)
        side=e.get("side")
        if side not in SIDES:
            raise ValueError("WAVE FORWARD: bledny kierunek zdarzenia.")
        signal=_utc(e.get("signal_utc"))
        outcomes=e.get("outcomes") or {}
        if not isinstance(outcomes,dict):
            raise ValueError("WAVE FORWARD: uszkodzone rozliczenia.")
        forward.append((side,signal,outcomes))
    by_side={side:[e for e in forward if e[0]==side] for side in SIDES}
    rows=[]
    for side,cohort in by_side.items():
        unique_sessions=len({signal.tz_convert(NY).date()
                             for _,signal,_ in cohort})
        for bars in HORIZONS:
            for threshold in THRESHOLDS:
                key=f"{bars*15}m_{threshold:g}pct"
                c={k:0 for k in CATEGORIES}
                resolved=invalidated=pending=bad=0
                for _,_,outcomes in cohort:
                    outcome=outcomes.get(key) or {}
                    status=outcome.get("status","PENDING")
                    if status=="CLOSED":
                        cat=_category(outcome)
                        if cat is None:
                            bad+=1
                        else:
                            c[cat]+=1
                            resolved+=1
                    elif isinstance(status,str) and status.startswith("INVALIDATED_"):
                        invalidated+=1
                    elif status=="PENDING":
                        pending+=1
                    else:
                        bad+=1
                # A single event is present in exactly one bin per condition.
                assert resolved+invalidated+pending+bad==len(cohort)
                rows.append({
                    "side":side,"minutes":bars*15,"threshold_pct":float(threshold),
                    "events":len(cohort),"sessions":unique_sessions,
                    "resolved":resolved,"invalidated":invalidated,
                    "pending":pending,"bad":bad,**c,
                })
    if reference is None:
        reference=load_reference_ranking()
    if not isinstance(reference,pd.DataFrame) or not set(
            BENCHMARK_COLS).issubset(reference.columns):
        raise ValueError("WAVE FORWARD: brak zamrozonego rankingu historycznego.")
    benchmark=reference.loc[:,list(BENCHMARK_COLS)].copy()
    benchmark=benchmark.sort_values(["LONG_SHORT","FORMACJA"]).reset_index(drop=True)
    return {
        "source_live":str(state.get("source","BRAK ZRODLA")),
        "source_history":"Dukascopy USA500.IDX/USD CFD",
        "last_closed_utc":state.get("last_closed_utc"),
        "forward_events":len(forward),
        "forward_sessions":len({s.tz_convert(NY).date() for _,s,_ in forward}),
        "retained_events":len(events),
        "cohorts":pd.DataFrame(rows),
        "reference":benchmark,
        "trade_permission":"WAIT",
        "calibrated_probability":False,
        "comparable_to_historical_ae":False,
        "reason":STATUS,
    }
