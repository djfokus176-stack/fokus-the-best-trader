"""Read-only causal audit of the last CLOSED M1 bars.

Explains what each of the six real strategies did on *each* prior candle.
No broker calls, no trade creation, no retrospective fills, no parameter
tuning or calendar/market override. Raw LONG/SHORT votes are already AFTER
each strategy's risk/room-to-target rules, before MTF. An apparent bounce
is not necessarily a rule-valid setup.
"""
from __future__ import annotations

from collections import Counter
import math

import pandas as pd

from .auto_strategy import evaluate_auto, vote_summary
from .mtf import TIMEFRAMES, evaluate_timeframes
from .strategy import indicators

MIN_HISTORY = 85
MAX_LOOKBACK = 40


def rejection_stage(reason: str) -> str:
    """Classify rejection; explanatory only, not used by trading decisions."""
    r = str(reason or "").lower()
    if "mtf" in r or "m5/m15/h1" in r:
        return "MTF"
    if "opór" in r or "wsparcie" in r or "room-to-target" in r:
        return "OPÓR / WSPARCIE"
    if "rr " in r or "stosunek zysku do ryzyka" in r or "geometria ryzyka" in r:
        return "RYZYKO / RR"
    if "spread" in r or "koszt" in r:
        return "KOSZT / SPREAD"
    if "świec" in r or "dane" in r or "atr niedostęp" in r:
        return "DANE"
    if "konflikt" in r:
        return "KONFLIKT KIERUNKÓW"
    if "brak" in r or "trend" in r:
        return "BRAK FORMACJI / TRENDU"
    return "INNY POWÓD"


def _validate(frame, timeframe_snapshots, lookback):
    if frame is None or not isinstance(frame, pd.DataFrame):
        raise ValueError("Brak historii zamkniętych świec M1.")
    if len(frame) < MIN_HISTORY:
        raise ValueError("Potrzeba co najmniej 85 zamkniętych świec M1.")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("M1 wymaga potwierdzonych znaczników czasu UTC.")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("M1 musi być chronologiczne i bez duplikatów.")
    if not {"Open","High","Low","Close","Spread"}.issubset(frame.columns):
        raise ValueError("Brak OHLC albo historycznego spreadu M1.")
    if not (1 <= lookback <= MAX_LOOKBACK):
        raise ValueError("Dozwolony zakres: 1–40 ostatnich zamkniętych świec.")
    if not isinstance(timeframe_snapshots, dict):
        raise ValueError("MTF musi być zestawem oddzielnych, zweryfikowanych interwałów.")
    import numpy as np
    data=frame[["Open","High","Low","Close","Spread"]]
    if not np.isfinite(data.to_numpy(dtype=float)).all():
        raise ValueError("Historia M1 zawiera NaN lub nieskończoność.")
    if (data["Spread"] < 0).any() or (data["Low"] > data[["Open","High","Close"]].min(axis=1)).any() or (data["High"] < data[["Open","Low","Close"]].max(axis=1)).any():
        raise ValueError("Wadliwa geometria OHLC lub spread M1.")


def audit_recent_closed_bars(frame: pd.DataFrame, snapshots: dict, *,
                             lookback: int = 20) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    """Causally replay one rule-evaluation for each historical closed M1 bar.

    The MTF filters see only HTF bars whose CLOSE <= signal-bar CLOSE.
    This is a diagnostic, NOT PAPER replay: historical BLS blackout,
    exact execution/spread dynamics and future trade fills are not recreated.
    """
    _validate(frame,snapshots,lookback)
    # Protect the owner from retrospectively reusing unrelated feeds.
    anchor = snapshots.get("MINUTE")
    mtf_matching = bool(
        anchor is not None and getattr(anchor, "resolution", None)=="MINUTE"
        and getattr(anchor,"good",False)
        and len(anchor.frame)>0 and frame.index[-1] in anchor.frame.index
        and frame.index[-1] <= anchor.frame.index[-1]
        and float(frame.Close.iloc[-1]) == float(anchor.frame.loc[frame.index[-1],"Close"]))
    if mtf_matching:
        mtf_matching = all(
            tf in snapshots and getattr(snapshots[tf],"good",False)
            and snapshots[tf].epic==anchor.epic
            and snapshots[tf].source==anchor.source
            and snapshots[tf].resolution==tf
            for tf in TIMEFRAMES)
    if not mtf_matching:
        # Never call evaluate_auto(use_mtf=False): that would present
        # vetoed/incomplete historical rows as hypothetical valid entries.
        mtf = {}
    else:
        mtf=snapshots
    full_ind=indicators(frame)
    timeline,details=[],[]
    start=max(MIN_HISTORY-1,len(frame)-lookback)
    for i in range(start,len(frame)):
        window=frame.iloc[:i+1]
        ts=window.index[-1]
        # Require 85 adjacent historical M1 CLOSE timestamps for this view;
        # a weekend/market-session gap within the lookback invalidates it.
        recent=window.index[-MIN_HISTORY:]
        if len(recent)>1 and not (recent.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all():
            timeline.append({
                "Świeca UTC":ts.isoformat(),"Close MID":round(float(frame.Close.iloc[i]),3),
                "Po MTF / surowe":"—","LONG":0,"SHORT":0,"Wynik":"BRAK DANYCH",
                "MTF":"BRAK","Przyczyna":"Luka M1 w 85 ostatnich zamkniętych świecach."})
            continue
        spread=float(frame.Spread.iloc[i])
        # use_mtf always TRUE; missing verified HTFs must remain a veto.
        decision,rows=evaluate_auto(window,spread,mtf,asof=ts.to_pydatetime(),use_mtf=True)
        counts=vote_summary(rows)
        views,consensus=evaluate_timeframes(mtf,asof=ts.to_pydatetime())
        mtf_ready=bool(mtf_matching and all(v.ready for v in views))
        row=full_ind.iloc[i]
        causes=Counter()
        for entry in rows:
            stage=("ZATWIERDZONY" if entry["Po filtrze MTF"] in ("LONG","SHORT")
                   else rejection_stage(entry["Powód"]))
            if stage!="ZATWIERDZONY":
                causes[stage]+=1
            details.append({
                "Świeca UTC":ts.isoformat(),"Strategia":entry["Strategia"],
                "Przed MTF":entry["Setup OHLC"],
                "Po MTF":entry["Po filtrze MTF"],
                "Etap":stage,
                "Powód":entry["Powód"],"RR":entry["RR"]})
        timeline.append({
            "Świeca UTC":ts.isoformat(),
            "Close MID":round(float(row.Close),3),
            "EMA9":round(float(row.EMA9),3),
            "EMA21":round(float(row.EMA21),3),
            "EMA50":round(float(row.EMA50),3),
            "RSI":round(float(row.RSI),1) if math.isfinite(float(row.RSI)) else None,
            "Spread":round(spread,3),
            "Po MTF / surowe":counts["label"],
            "LONG":counts["long"],"SHORT":counts["short"],
            "Wynik":decision.action if mtf_ready else "WAIT / MTF NIEZWERYFIKOWANE",
            "MTF":consensus if mtf_ready else "BRAK",
            "Przyczyna":(
                "MTF niepełne/nieaktualne; żadnego historycznego zatwierdzenia."
                if not mtf_ready else
                decision.reason[:220] if decision.action=="WAIT" else
                "Hipotetyczny setup: "+decision.strategy),
        })
    summary={
        "analysed_bars":len(timeline),
        "fully_ready_mtf":sum(x.get("MTF")!="BRAK" for x in timeline),
        "historical_long_candidates":sum(x.get("Wynik")=="LONG" for x in timeline),
        "historical_short_candidates":sum(x.get("Wynik")=="SHORT" for x in timeline),
        "raw_signal_bars":sum(x.get("Po MTF / surowe","0/0").split("/")[-1].isdigit() and int(x["Po MTF / surowe"].split("/")[-1])>0 for x in timeline),
        "confirmed_utc":frame.index[-1].isoformat(),
        "scope":"HISTORYCZNY AUDYT REGUŁ, NIE wykonane PAPER, BEZ retrospektywnego kalendarza ani weryfikacji egzekucji",
    }
    return pd.DataFrame(timeline),pd.DataFrame(details),summary
