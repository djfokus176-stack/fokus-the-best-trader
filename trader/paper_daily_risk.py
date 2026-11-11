"""Non-broker daily drawdown circuit breaker for simulated PAPER entries.

After a completed PAPER position, a configurable cap pauses NEW PAPER
PENDING signals for the rest of the Europe/Warsaw calendar day. This never
modifies OPEN positions or the existing SL/TP/TIMEOUT accounting.

Drawdown = worst fall from the day's peak cumulative net PAPER P&L (starting
at zero), not just net loss at the latest timestamp. Once breached it stays
latched for the rest of that day. It does NOT limit an individual gap/stop
loss, guarantee a daily worst loss, or imply a profitable strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd


WARSAW=ZoneInfo("Europe/Warsaw")
CLOSED=("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")
DEFAULT_DAILY_STOP_PTS=20.0


@dataclass(frozen=True)
class PaperDailyRisk:
    day: str
    closed_count: int
    realized_pts: float
    max_drawdown_pts: float
    limit_pts: float
    blocked: bool


def paper_daily_risk(db, *, epic:str, source:str, asof,
                     max_drawdown_pts:float=DEFAULT_DAILY_STOP_PTS)->PaperDailyRisk:
    """Only completed, dated historical positions known as of the M1 candle.

    A disabled limit of 0 requires deliberate env configuration. Missing
    data or PENDING / OPEN / INVALIDATED do not count as losses.
    """
    from .paper_lifecycle import ensure_tables
    limit=float(max_drawdown_pts)
    if not isfinite(limit) or limit<0:
        raise ValueError("PAPER daily stop wymaga liczby >=0 pkt.")
    t=pd.Timestamp(asof)
    if t.tzinfo is None:
        raise ValueError("PAPER daily stop wymaga czasu ze strefą UTC.")
    t=t.tz_convert("UTC")
    day=t.tz_convert(WARSAW).date()
    # Query by source and instrument only: day is assigned by *CLOSING*
    # timestamp converted to Warsaw, not setup or entry time.
    ensure_tables(db)
    rows=db.execute("""SELECT closed_utc,pnl_pts,trade_id
           FROM paper_positions_v3
           WHERE epic=? AND source=? AND status IN ('CLOSED_SL',
           'CLOSED_TP','CLOSED_TIMEOUT') AND closed_utc IS NOT NULL
           AND pnl_pts IS NOT NULL""",(epic,source)).fetchall()
    finished=[]
    for stamp,pnl,trade_id in rows:
        try:
            closed_at=pd.Timestamp(stamp)
            amount=float(pnl)
        except (ValueError,TypeError,OverflowError):
            continue
        if (closed_at.tzinfo is None or not isfinite(amount)
                or closed_at.tz_convert(WARSAW).date()!=day
                or closed_at.tz_convert("UTC")>t):
            continue
        finished.append((closed_at.tz_convert("UTC"),str(trade_id),amount))
    finished.sort(key=lambda x:(x[0],x[1]))
    cumulative=0.
    peak=0.
    max_dd=0.
    for _,_,pnl in finished:
        cumulative+=pnl
        peak=max(peak,cumulative)
        max_dd=max(max_dd,peak-cumulative)
    # 0 is explicitly disabled; the cap is inclusive at first breach.
    return PaperDailyRisk(
        day=day.isoformat(),closed_count=len(finished),
        realized_pts=round(cumulative,3),
        max_drawdown_pts=round(max_dd,3),limit_pts=limit,
        blocked=limit>0 and max_dd+1e-9>=limit)
