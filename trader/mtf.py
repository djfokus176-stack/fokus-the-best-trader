"""Multi-timeframe (MTF) context from FOUR independent, CLOSED Capital.com series.

No interpolation of M1 into higher timeframes and no silent Yahoo fallback.
Snapshots must belong to the same instrument/source and pass freshness checks.
An HTF candle with a timestamp newer than the M1 evaluation bar is excluded.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from .market import PERIOD
from .strategy import indicators, Decision
from .runtime import current_feed_status

TIMEFRAMES = ("MINUTE", "MINUTE_5", "MINUTE_15", "HOUR")
LABELS = {"MINUTE": "M1", "MINUTE_5": "M5", "MINUTE_15": "M15", "HOUR": "H1"}


@dataclass(frozen=True)
class TFView:
    timeframe: str
    trend: str
    close: float | None
    atr: float | None
    rsi: float | None
    ready: bool
    reason: str
    candle_utc: object = None


def trend_from_closed(frame: pd.DataFrame) -> str:
    if frame is None or len(frame) < 70:
        return "UNKNOWN"
    d = indicators(frame)
    row = d.iloc[-1]
    if pd.isna(row.ATR) or row.ATR <= 0:
        return "UNKNOWN"
    if row.EMA9 > row.EMA21 > row.EMA50:
        return "UP"
    if row.EMA9 < row.EMA21 < row.EMA50:
        return "DOWN"
    return "NEUTRAL"


def evaluate_timeframes(snapshots: dict, now=None, asof=None) -> tuple[list[TFView], str]:
    """Fail closed on missing, stale, mismatched or future HTF observations."""
    anchor = snapshots.get("MINUTE")
    anchor_time = getattr(anchor, "confirmed_utc", None)
    if anchor_time is not None and asof is not None:
        anchor_time = min(anchor_time, asof)
    if anchor_time is None:
        return [TFView(tf,"UNKNOWN",None,None,None,False,"Brak świec M1") for tf in TIMEFRAMES], "WAIT"
    rows = []
    for tf in TIMEFRAMES:
        sn = snapshots.get(tf)
        if sn is None:
            rows.append(TFView(tf, "UNKNOWN",None,None,None,False,"Nie pobrano świec"))
            continue
        ready, reason, _ = current_feed_status(sn, sn.source, now)
        if sn.epic != anchor.epic or sn.source != anchor.source or sn.resolution != tf:
            ready, reason = False, "Niezgodny instrument, interwał lub źródło"
        # Future bars in a fetched HTF series are never included in calculations.
        frame = sn.frame.loc[sn.frame.index <= pd.Timestamp(anchor_time)]
        if len(frame) < 70:
            ready, reason = False, "Za mało potwierdzonych świec"
        trend = trend_from_closed(frame)
        if trend == "UNKNOWN":
            ready, reason = False, "Brak wskaźników"
        last = indicators(frame).iloc[-1] if len(frame)>=70 else None
        rows.append(TFView(tf, trend, float(last.Close) if last is not None else None,
            round(float(last.ATR), 3) if last is not None else None,
            round(float(last.RSI), 2) if last is not None else None,
            bool(ready), reason, sn.confirmed_utc))
    if not all(r.ready for r in rows):
        return rows, "WAIT"
    ups = sum(r.trend == "UP" for r in rows[1:])
    downs = sum(r.trend == "DOWN" for r in rows[1:])
    if ups >= 2 and downs == 0:
        return rows, "UP"
    if downs >= 2 and ups == 0:
        return rows, "DOWN"
    return rows, "NEUTRAL"


def filter_mtf_decision(decision: Decision, snapshots: dict, now=None, asof=None) -> tuple[Decision, list[TFView]]:
    """MTF never invents a signal, only allows or vetoes a base strategy."""
    rows, consensus = evaluate_timeframes(snapshots, now, asof=asof)
    if decision.action not in ("LONG","SHORT"):
        return decision, rows
    need = "UP" if decision.action=="LONG" else "DOWN"
    if consensus != need:
        from dataclasses import replace
        decision=replace(decision, action="WAIT", entry=None, stop=None,
                         target=None, rr=None,
                         reason="MTF: brak zgodności M5/M15/H1 lub nieaktualne dane")
    return decision, rows


def fetch_all_timeframes(client, epic: str, max_spread: float=2.0, count: int=250):
    """Four read-only candle queries; explicit per-timeframe error reporting."""
    from .market import FeedError
    snapshots, failures = {}, {}
    for tf in TIMEFRAMES:
        try:
            snapshots[tf] = client.candles(epic, tf, count=count, max_spread=max_spread)
        except (FeedError, ValueError, TypeError) as exc:
            failures[tf] = str(exc)[:250]
    return snapshots, failures
