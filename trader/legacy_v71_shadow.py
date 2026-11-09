"""Read-only reconstruction of SP500 SIGNAL AI PRO v7.1 ENTRY conditions.

Source: djfokus176-stack/sp500-kolega-gemini/app.py
        detect_signals_and_waves(), lines ~587-777 (9 Nov 2026).
The legacy UI also draws replay/history arrows and tracks exits; this module
intentionally evaluates ONLY the latest *fully closed* M1 entry hypothesis.
It neither makes a next-bar fill, nor queues PAPER, nor places broker orders.

Use full closed Capital.com M5 for its older M5 EMA9/21 trend filter.
Historical v7.1 used shift(1) because the latest M5 could be forming;
new FOKUS M5 snapshot already removes the forming bar, so do not shift again.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

LEGACY_V71_LABEL = "SP500 SIGNAL AI PRO v7.1 — LEGACY SHADOW"
LEGACY_V71_SOURCE = "djfokus176-stack/sp500-kolega-gemini/app.py"
DEFAULT_SENSITIVITY = "Tylko Pewniaki (Filtr Konsolidacji)"
SENSITIVITIES = (DEFAULT_SENSITIVITY, "Standard (Z filtrem płaskich EMA)",
                 "Wysoka (Więcej strzałek)")


@dataclass(frozen=True)
class LegacyV71Shadow:
    action: str
    pattern: str
    reason: str
    close_mid: float | None = None
    rsi: float | None = None
    atr: float | None = None
    m5_bias: str = "UNKNOWN"


def _wait(reason, *, m5_bias="UNKNOWN", close=None, rsi=None, atr=None):
    return LegacyV71Shadow("WAIT", "-", reason, close, rsi, atr, m5_bias)


def evaluate_v71_shadow(frame: pd.DataFrame, m5_closed: pd.DataFrame | None,
                        spread: float, *, sensitivity: str = DEFAULT_SENSITIVITY
                        ) -> LegacyV71Shadow:
    """Historical v7.1 signal rule on one latest confirmed M1 candle.

    Does not claim to replicate the legacy position/exits state machine.
    No access to future bars, broker actions or persistent state.
    """
    if sensitivity not in SENSITIVITIES:
        return _wait("Nieznany wariant czułości starego programu.")
    if frame is None or m5_closed is None or len(frame) < 60 or len(m5_closed) < 22:
        return _wait("Brak minimum 60 zamkniętych M1 oraz 22 zamkniętych M5.")
    try:
        spread = float(spread)
    except (TypeError, ValueError):
        return _wait("Brak prawidłowego spreadu.")
    if not math.isfinite(spread) or spread < 0:
        return _wait("Nieprawidłowy spread.")
    try:
        base = frame[["Open", "High", "Low", "Close"]].copy().sort_index()
        higher = m5_closed[["Close"]].copy().sort_index()
        if (not base.index.is_unique or not higher.index.is_unique
                or base.index.tz is None or higher.index.tz is None):
            return _wait("Niezweryfikowane lub powtórzone znaczniki czasu świec.")
        anchor = base.index[-1]
        # No M5 bar newer than the closed M1 signal candle.
        higher = higher.loc[higher.index <= anchor]
        if len(higher) < 22:
            return _wait("Brak zakończonej świecy M5 dla czasu sygnału.")
        # Existing feed snapshots are already closed; no synthetic M5.
        values = np.asarray(base.to_numpy(dtype=float), dtype=float)
        hvals = higher.Close.to_numpy(dtype=float)
        if not (np.isfinite(values).all() and np.isfinite(hvals).all()):
            return _wait("Niefinitywne OHLC lub M5 (NaN/Inf).")
        if ((base.High < base[["Open", "Close", "Low"]].max(axis=1)).any()
                or (base.Low > base[["Open", "Close", "High"]].min(axis=1)).any()):
            return _wait("Błędna geometria świecy OHLC.")
    except (KeyError, TypeError, ValueError, AttributeError):
        return _wait("Niepoprawny format zamkniętych świec.")
    for span in (9, 21, 50):
        base[f"EMA{span}"] = base.Close.ewm(span=span, adjust=False).mean()
    diff = base.Close.diff()
    up = diff.where(diff > 0, 0).rolling(14).mean()
    down = (-diff.where(diff < 0, 0)).rolling(14).mean()
    # Intentionally preserve v7.1 RSI behavior (flat 50 for zero loss).
    rsi = (100 - 100 / (1 + up / down.replace(0, np.nan))).fillna(50)
    true_range = pd.concat([
        base.High-base.Low, (base.High-base.Close.shift()).abs(),
        (base.Low-base.Close.shift()).abs()], axis=1).max(axis=1)
    atr_series = true_range.rolling(14, min_periods=14).mean()
    h9 = higher.Close.ewm(span=9, adjust=False).mean().iloc[-1]
    h21 = higher.Close.ewm(span=21, adjust=False).mean().iloc[-1]
    bias = "UP" if h9 > h21 else ("DOWN" if h9 < h21 else "NEUTRAL")
    a, prev = base.iloc[-1], base.iloc[-2]
    o,h,l,c = (float(a[x]) for x in ("Open","High","Low","Close"))
    po,pc = float(prev.Open),float(prev.Close)
    e9,e21,e50 = float(a.EMA9),float(a.EMA21),float(a.EMA50)
    atr = float(atr_series.iloc[-1])
    current_rsi = float(rsi.iloc[-1])
    if not math.isfinite(atr) or atr <= 0 or not math.isfinite(current_rsi):
        return _wait("Brak ATR/RSI starej metody.",m5_bias=bias)
    body, candle_range = abs(c-o), max(h-l, 0.01)
    upper_wick = h-max(o,c)
    lower_wick = min(o,c)-l
    wick_ratio = 1.4 if sensitivity==SENSITIVITIES[2] else 1.7
    min_atr_mult, min_slope_mult = 0.15, 0.20
    gap, e9_slope = abs(e9-e21), e9-float(base.EMA9.iloc[-4])
    e21_slope = e21-float(base.EMA21.iloc[-4])
    if (sensitivity != SENSITIVITIES[2] and
            gap < atr*min_atr_mult and abs(e9_slope)<atr*min_slope_mult):
        return _wait("Stary filtr: płaskie EMA / konsolidacja.",
                     m5_bias=bias,close=c,rsi=current_rsi,atr=atr)
    bull_pin=(lower_wick >= body*wick_ratio and lower_wick >= candle_range*.4
              and (c-l)/candle_range >= .55 and c>o)
    bull_eng=(pc<po and c>o and c>po and body>=atr*.35)
    bull_pull=(l<=e21 and c>e9 and c>o and (c-l)/candle_range>=.55)
    bull_wave=(c>o and c>e9 and e9>e21 and
               float(base.EMA9.iloc[-3])<=float(base.EMA21.iloc[-3]))
    bear_pin=(upper_wick>=body*wick_ratio and upper_wick>=candle_range*.4
              and (h-c)/candle_range>=.55 and c<o)
    bear_eng=(pc>po and c<o and c<po and body>=atr*.35)
    bear_pull=(h>=e21 and c<e9 and c<o and (h-c)/candle_range>=.55)
    bear_wave=(c<o and c<e9 and e9<e21 and
               float(base.EMA9.iloc[-3])>=float(base.EMA21.iloc[-3]))
    trend_up=(e9>e21 and c>e50 and e9_slope>0 and e21_slope>=0)
    trend_down=(e9<e21 and c<e50 and e9_slope<0 and e21_slope<=0)
    if sensitivity==DEFAULT_SENSITIVITY:
        # Fail closed without a confirmed M5 direction.
        trend_up = trend_up and bias=="UP"
        trend_down = trend_down and bias=="DOWN"
    if trend_up and 42<=current_rsi<=72:
        flags=[("pin bar",bull_pin),("objęcie hossy",bull_eng),
               ("odbicie EMA21",bull_pull),("fala EMA9/21",bull_wave)]
        match=next((label for label,ok in flags if ok),None)
        if match:
            return LegacyV71Shadow("LONG",match,"Układ v7.1: formacja + trend EMA + RSI. TYLKO SHADOW.",
                                   c,current_rsi,atr,bias)
    if trend_down and 28<=current_rsi<=58:
        flags=[("pin bar",bear_pin),("objęcie bessy",bear_eng),
               ("odbicie EMA21",bear_pull),("fala EMA9/21",bear_wave)]
        match=next((label for label,ok in flags if ok),None)
        if match:
            return LegacyV71Shadow("SHORT",match,"Układ v7.1: formacja + trend EMA + RSI. TYLKO SHADOW.",
                                   c,current_rsi,atr,bias)
    if not (trend_up or trend_down):
        reason="Brak wymaganego kierunku EMA i/lub potwierdzenia M5."
    elif not (42<=current_rsi<=72 or 28<=current_rsi<=58):
        reason="RSI poza przedziałem starej metody."
    else:
        reason="Brak pin bara, objęcia, odbicia od EMA21 lub fali EMA."
    return _wait(reason,m5_bias=bias,close=c,rsi=current_rsi,atr=atr)
