"""On-demand, read-only A–E replay from archived Capital.com DEMO M15.

Same A–E research engine as five-year study; fresh feed and execution model
differ (no full BID/ASK), so this is an exploratory diagnostic only.
No remote writes, no broker queries, no orders, no live strategy promotion.
"""
from __future__ import annotations

import pandas as pd

from .wave_reversal import validate_closed_m15
from .wave_intelligence2 import run_wave_abcd

MAX_BARS=3000
SOURCE="Capital.com DEMO REST"
DECISION="WAIT — BRAK NOWEGO, NIEZALEŻNEGO OOS"


def research_capital_ae(frame:pd.DataFrame, *, source=SOURCE,
                        slippage=.25, rr=1.5, hold_minutes=120) -> dict:
    if source!=SOURCE:
        raise ValueError("WAVE A–E: tylko archiwum Capital.com DEMO REST.")
    if not isinstance(frame,pd.DataFrame) or not 210<=len(frame)<=MAX_BARS:
        raise ValueError("WAVE A–E: wymaga od 210 do 3000 M15 z Supabase.")
    validate_closed_m15(frame)
    if "Spread" not in frame.columns:
        raise ValueError("WAVE A–E: wymagane historyczne spready Capital.")
    spread=pd.to_numeric(frame["Spread"],errors="raise")
    if spread.isna().any() or (spread<0).any() or not spread.map(
            lambda v: bool(pd.notna(v) and float("-inf")<float(v)<float("inf"))).all():
        raise ValueError("WAVE A–E: niepoprawne historyczne spready.")
    if not (0<=slippage<=10 and rr in (1.,1.5,2.,3.) and
            hold_minutes in (30,45,60,120)):
        raise ValueError("WAVE A–E: niedozwolone zalozenia symulacji.")
    # Recorded per-candle Spread takes precedence over constant fallback,
    # as in the historical research engine; it is NOT true full BID/ASK.
    summary,logs,meta=run_wave_abcd(
        frame,spread=2.,slippage=slippage,rr=rr,
        hold_minutes=hold_minutes)
    aggregate=summary.loc[summary["year"].isna()].copy()
    metadata={
        "source":SOURCE,"timeframe":"M15",
        "first_close_utc":frame.index[0].isoformat(),
        "last_close_utc":frame.index[-1].isoformat(),
        "stored_candles":len(frame),
        "mode":"LAST_KNOWN_CLOSE_SPREAD_MODEL",
        "slippage_per_side":slippage,"rr":rr,"hold_minutes":hold_minutes,
        "anchors":meta.get("anchors",0),
        "cutoff_exploratory":meta.get("oos_cutoff"),
        "trade_permission":"WAIT",
        "calibrated_probability":False,
        "new_independent_oos":False,
        "fully_comparable_to_dukascopy":False,
        "reason":DECISION,
    }
    return {"summary":aggregate,"logs":logs,"meta":metadata}
