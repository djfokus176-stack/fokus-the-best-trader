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


def compare_clock_observations(previous: dict, latest: dict) -> dict:
    """Two manual raw DEMO reads. Evidence, NOT automatic trading approval."""
    if not previous or not latest or previous.get("resolution")!=latest.get("resolution"):
        return {"status":"BRAK DWÓCH PORÓWNYWALNYCH ODCZYTÓW"}
    if latest.get("resolution") not in PERIOD:
        return {"status":"NIEZNANY INTERWAL"}
    step=PERIOD[latest["resolution"]]
    try:
        old_label=pd.Timestamp(previous["last_label_utc"])
        new_label=pd.Timestamp(latest["last_label_utc"])
        older=pd.Timestamp(previous["observed_utc"])
        newer=pd.Timestamp(latest["observed_utc"])
    except (KeyError,TypeError,ValueError):
        return {"status":"BRAK PRAWIDŁOWYCH CZASÓW"}
    if newer<=older or new_label<=old_label:
        return {"status":"BRAK NOWEJ ŚWIECY — wykonaj kolejny odczyt po zmianie interwału"}
    old_lag=(older-old_label).total_seconds()
    new_lag=(newer-new_label).total_seconds()
    if 0<=old_lag<step and 0<=new_lag<step and (
            new_label-old_label).total_seconds()%step==0:
        return {
          "status":"DWIE OBSERWACJE WSPIERAJĄ OPEN",
          "prev_label_utc":old_label.isoformat(),
          "new_label_utc":new_label.isoformat(),
          "note":"Przesłanka empiryczna z DEMO, nie oficjalne potwierdzenie. Sprawdź też wykres brokera."}
    return {"status":"NIEJEDNOZNACZNE — nie włączaj PAPER",
            "prev_age_seconds":round(old_lag,1),
            "next_age_seconds":round(new_lag,1)}
