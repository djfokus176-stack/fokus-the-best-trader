"""Causal structural obstacles for PAPER research, NOT production defaults.

A pivot needs LEFT older and RIGHT newer CLOSED bars to be known. The
evaluated signal bar is never included. Missing confirmed pivots means
"no level found", NOT proof the target is free of real-world obstacles.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
import pandas as pd


@dataclass(frozen=True)
class StructuralRoom:
    blocked: bool
    level: float | None
    distance: float | None
    confirmed_count: int
    reason: str


def structural_room(frame: pd.DataFrame, side: str, entry: float,
                    risk: float, min_rr: float = 1.35, *, lookback: int = 90,
                    left: int = 2, right: int = 2) -> StructuralRoom:
    if side not in ("LONG", "SHORT") or not all(isfinite(float(x))
            for x in (entry, risk, min_rr)) or risk <= 0 or min_rr <= 0:
        raise ValueError("Nieprawidłowa geometria testu swing high/low.")
    if frame is None or len(frame) < left + right + 3:
        return StructuralRoom(False, None, None, 0, "Za mało zamkniętych M1 do poziomów.")
    from .market_dna import confirmed_pivots
    # The newest signal candle must not help confirm earlier pivots or
    # be used as an obstacle itself. Only already-closed bars before it.
    past = frame.iloc[:-1].tail(lookback)
    highs, lows = confirmed_pivots(past, left=left, right=right)
    levels = ([price for _, price in highs if price > entry]
              if side == "LONG" else
              [price for _, price in lows if price < entry])
    if not levels:
        return StructuralRoom(False, None, None, 0, "Brak potwierdzonego swingu przed celem.")
    nearest = float(min(levels) if side == "LONG" else max(levels))
    distance = nearest-entry if side == "LONG" else entry-nearest
    return StructuralRoom(distance < min_rr*risk, nearest,
                          round(distance, 4), len(levels),
                          "Potwierdzony swing ogranicza miejsce na TP."
                          if distance < min_rr*risk
                          else "Potwierdzone swingi nie blokują minimalnego RR.")
