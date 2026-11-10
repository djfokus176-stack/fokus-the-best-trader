"""Build a safe research-only CSV from owner-authorized Supabase OHLC.

No secrets are included; caller already fetched read-only closed Capital DEMO
M1 candles through RemoteCheckpoint.fetch_candles. Validate timestamp
convention and OHLC before offering the file for offline MTF comparison.
"""
from __future__ import annotations

import pandas as pd
from .mtf_replay import validate_close_time_m1, build_higher_closed_bars


def research_csv_from_closed_m1(frame: pd.DataFrame) -> dict:
    validate_close_time_m1(frame)
    if len(frame)>5000:
        raise ValueError("Eksport maksymalnie 5000 ostatnich świec M1.")
    if len(frame)<2:
        raise ValueError("Za mało zamkniętych M1 do eksportu.")
    closed=frame[["Open","High","Low","Close","Spread"]].copy()
    closed.index.name="Time"
    data=closed.reset_index().to_csv(index=False).encode("utf-8-sig")
    complete=build_higher_closed_bars(closed)
    gaps=int((closed.index.to_series().diff()>pd.Timedelta(minutes=1)).sum())
    full_h1=len(complete["HOUR"])
    return {
        "csv":data,"count":len(closed),
        "first":closed.index[0].isoformat(),
        "last":closed.index[-1].isoformat(),
        "gaps":gaps,"full_h1":full_h1,
        "preflight_mtf":len(closed)>=4600 and full_h1>=70,
    }
