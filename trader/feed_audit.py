"""Capital.com candle timestamp audit. No speculative assumption is hidden.

A single response can be CONSISTENT with open- or close-labeled OHLC,
but only broker confirmation or two independently observed bar updates can
establish semantics reliably. No trading decision is made from this audit.
"""
from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd
from .market import PERIOD

def inspect_labels(frame,resolution,observed_at=None):
    if resolution not in PERIOD:
        raise ValueError("Unknown timeframe")
    if frame is None or frame.empty or frame.index.tz is None:
        raise ValueError("Missing timezone-aware OHLC")
    now=pd.Timestamp(observed_at or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("aware UTC timestamp required")
    sec=PERIOD[resolution]
    last=pd.Timestamp(frame.index[-1])
    delta=float((now-last).total_seconds())
    if 0<=delta<sec:
        hypothesis="ZGODNE Z CZASEM OTWARCIA (NIE POTWIERDZONE)"
    elif -sec<=delta<0:
        hypothesis="ZGODNE Z CZASEM ZAMKNIĘCIA (NIE POTWIERDZONE)"
    else:
        hypothesis="NIEROZSTRZYGNIĘTE: brak świeżości, przerwa sesyjna lub inna konwencja"
    return {"resolution":resolution,"observed_utc":now.isoformat(),
            "last_label_utc":last.isoformat(),"age_seconds":round(delta,2),
            "time_hypothesis":hypothesis,
            "raw_last_four_labels_utc":[str(t) for t in frame.index[-4:]],
            "verification":"NIEZWERYFIKOWANE — porównaj z zegarem brokera i nowymi świecami"}
