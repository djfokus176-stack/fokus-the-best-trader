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
        # For historical asof the latest usable HTF candle is NOT the
        # newest candle in the fetched snapshot. Reject gaps and never
        # reuse a stale historical trend as if it were contemporaneous.
        actual_closed = frame.index[-1] if len(frame) else None
        if actual_closed is not None:
            lag_seconds=(pd.Timestamp(anchor_time)-actual_closed).total_seconds()
            if lag_seconds<0 or lag_seconds>=PERIOD[tf]:
                ready,reason=False,"Brak współczesnej zamkniętej świecy "+LABELS[tf]
        if len(frame) < 70:
            ready, reason = False, "Za mało potwierdzonych świec"
        trend = trend_from_closed(frame)
        if trend == "UNKNOWN":
            ready, reason = False, "Brak wskaźników"
        last = indicators(frame).iloc[-1] if len(frame)>=70 else None
        rows.append(TFView(tf, trend, float(last.Close) if last is not None else None,
            round(float(last.ATR), 3) if last is not None else None,
            round(float(last.RSI), 2) if last is not None else None,
            bool(ready), reason, actual_closed))
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


def timeframe_refresh_needed(snapshot, timeframe: str, *, elapsed: float,
                             anchor_closed=None, retry_after: float=58.) -> bool:
    """Refresh cached HTF when a newer CLOSED interval is due or data failed.

    Bounded by retry_after seconds to avoid retry storms / Capital.com 429.
    Never turns a stale HTF into an accepted MTF result by itself.
    """
    if timeframe not in PERIOD:
        raise ValueError("Nieznany interwał MTF")
    # A missing snapshot is not permission to hammer Capital.com after
    # HTTP 429/network errors. The UI records the time of *every attempt*.
    # A genuinely never-attempted TF is passed elapsed=inf for immediate boot.
    if elapsed < retry_after:
        return False
    if snapshot is None:
        return True
    if elapsed >= max(60,PERIOD[timeframe])-2:
        return True
    if not getattr(snapshot,"good",False):
        return True
    if anchor_closed is None or getattr(snapshot,"confirmed_utc",None) is None:
        return True
    try:
        lag=(pd.Timestamp(anchor_closed)-pd.Timestamp(snapshot.confirmed_utc)).total_seconds()
    except (TypeError,ValueError):
        return True
    if lag < 0 or lag >= PERIOD[timeframe]:
        return True
    return not current_feed_status(snapshot,snapshot.source)[0]


def _validated_h1_forming_spread_with_m1(snapshots, max_spread: float):
    """Only reconcile an H1 *forming-quote* discrepancy against verified M1.

    H1 CLOSED bid/ask spread, OHLC structure, age, source and MTF alignment
    remain mandatory. Never substitute M1 bars for H1 indicators, never
    relax the live M1 spread gate, and never repair any broker data.
    """
    from dataclasses import replace
    import math
    import re
    from .market import Snapshot, _unexpected_recent_gap

    h1=snapshots.get("HOUR")
    m1=snapshots.get("MINUTE")
    if not (isinstance(h1,Snapshot) and isinstance(m1,Snapshot)
            and not h1.good and m1.good):
        return h1
    match=re.fullmatch(r"Bieżący spread: ([0-9]+(?:\.[0-9]+)?) > ([0-9]+(?:\.[0-9]+)?)",
                       str(h1.reason))
    if not match:
        return h1
    if (h1.epic!="US500" or m1.epic!=h1.epic
            or h1.source!="Capital.com DEMO REST" or m1.source!=h1.source
            or h1.resolution!="HOUR" or m1.resolution!="MINUTE"):
        return h1
    try:
        if not all(math.isfinite(float(x)) for x in (
                max_spread,h1.quote_spread,h1.spread,
                m1.quote_spread,m1.spread,h1.age_seconds,m1.age_seconds)):
            return h1
        if (float(max_spread)<=0
                or abs(float(match.group(1))-float(h1.quote_spread))>0.011
                or abs(float(match.group(2))-float(max_spread))>0.011
                or not (float(h1.quote_spread)>max_spread
                        and 0<=float(h1.spread)<=max_spread
                        and 0<=float(m1.quote_spread)<=max_spread
                        and 0<=float(m1.spread)<=max_spread)):
            return h1
        # The original snapshot stops at the forming-quote check, so redo
        # the downstream stale/OHLC/recent-gap checks before accepting it.
        if not (-PERIOD["MINUTE"] <= m1.age_seconds
                <= 3*PERIOD["MINUTE"]+60
                and -PERIOD["HOUR"] <= h1.age_seconds
                <= 3*PERIOD["HOUR"]+60):
            return h1
        if h1.confirmed_utc is None or m1.confirmed_utc is None:
            return h1
        lag=(pd.Timestamp(m1.confirmed_utc)
             -pd.Timestamp(h1.confirmed_utc)).total_seconds()
        if not (0<=lag<PERIOD["HOUR"]):
            return h1
        frame=h1.frame
        if (not isinstance(frame,pd.DataFrame) or len(frame)<70
                or frame.index.tz is None
                or not frame.index.is_monotonic_increasing
                or frame.index.has_duplicates
                or _unexpected_recent_gap(frame.index,"HOUR")):
            return h1
        tail=frame[["Open","High","Low","Close"]].tail(25)
        for values in tail.itertuples(index=False,name=None):
            o,high,low,close=map(float,values)
            if (not all(math.isfinite(v) for v in (o,high,low,close))
                    or low<=0 or high<max(o,close,low)
                    or low>min(o,close,high)):
                return h1
    except (TypeError,ValueError,AttributeError,KeyError,OverflowError):
        return h1
    return replace(h1,good=True,reason=(
        "OK: H1_CLOSED_OHLC_VALID; H1_FORMING_QUOTE_SPREAD_DISCREPANCY; "
        "M1_CURRENT_SPREAD_VERIFIED; NO_OHLC_REPAIR"))


def fetch_all_timeframes(client, epic: str, max_spread: float=2.0, count: int=250):
    """Fetch four broker TFs; re-check old corrupt history without bypassing QC.

    Capital /prices can return a long history containing crossed bid/ask bars.
    A single bounded SHORTER REST re-read may recover an independently valid,
    recent >=70-closed-candle tail. We never repair, interpolate, merge, or
    synthesize candles. If the shorter snapshot fails ANY normal validator,
    retain the original bad snapshot and let the worker block PAPER.
    """
    from .market import FeedError
    snapshots, failures = {}, {}
    for tf in TIMEFRAMES:
        try:
            snapshot = client.candles(epic, tf, count=count,
                                      max_spread=max_spread)
        except (FeedError, ValueError, TypeError) as exc:
            failures[tf] = str(exc)[:250]
            continue
        reason = str(getattr(snapshot, "reason", ""))
        corrupt_history = ("DANE_WADLIWE" in reason
                           or "odrzucono wadliwych rekordów" in reason)
        if (count >= 100 and not snapshot.good and corrupt_history):
            # Exactly one additional read; don't hammer the provider on
            # spreads, stale prices, normal WAIT, network failures or 429s.
            try:
                clean = client.candles(epic, tf, count=96,
                                       max_spread=max_spread)
            except (FeedError, ValueError, TypeError):
                clean = None
            if (clean is not None and clean.good
                    and clean.epic == snapshot.epic == epic
                    and clean.source == snapshot.source
                    and clean.resolution == snapshot.resolution == tf
                    and clean.confirmed_utc is not None
                    and (snapshot.confirmed_utc is None
                         or clean.confirmed_utc >= snapshot.confirmed_utc)
                    and len(clean.frame) >= 70):
                # Preserve an explicit diagnostic: the longer vendor history
                # was corrupt, even though a fresh short re-read passed QC.
                clean.reason += " RECHECK_CLEAN_TAIL=96_AFTER_CORRUPT_HISTORY"
                snapshot = clean
        snapshots[tf] = snapshot
    # The provider's forming H1 Close bid/ask may disagree with the currently
    # validated M1 quote. Never let that *single* non-signal field veto clean
    # H1 closed OHLC if strict M1 + H1 cross-checks above all pass.
    checked=_validated_h1_forming_spread_with_m1(snapshots,max_spread)
    if checked is not None:
        snapshots["HOUR"]=checked
    return snapshots, failures
