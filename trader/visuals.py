"""Historical PAPER markers on the same completed OHLC candles as the chart.
Research annotations only; never pretend they are executable brokerage trades.
"""
from __future__ import annotations
import pandas as pd
from .strategies_pro import decide_any

def historical_marks(frame: pd.DataFrame, strategy: str, max_bars: int = 110) -> pd.DataFrame:
    columns = ["time", "action", "price", "reason"]
    if frame is None or len(frame) < 72:
        return pd.DataFrame(columns=columns)
    events = []
    first = max(70, len(frame) - max_bars)
    for i in range(first, len(frame)):
        spread = float(frame["Spread"].iloc[i]) if "Spread" in frame else float("nan")
        if not (0 <= spread <= 20):
            continue
        d = decide_any(frame.iloc[:i+1], strategy, spread=spread)
        if d.action not in ("LONG", "SHORT") or d.entry is None:
            continue
        events.append({"time":frame.index[i], "action":d.action,
                       "price":float(frame.Low.iloc[i]) if d.action=="LONG" else float(frame.High.iloc[i]),
                       "reason":d.reason})
    return pd.DataFrame(events, columns=columns)
