"""Independent, forward-only RAW M1 PAPER: test genuine strategy signals vetoed by MTF.

No broker orders. Does NOT change original AUTO/MTF/PAPER v3 nor Momentum
PAPER TEST. Only actual RAW LONG/SHORT hypotheses on completed M1 candles,
after existing worker global data, news, account and risk blockers pass.
MARKERS and P&L are backed by durable chronological OPEN/CLOSED events;
never infer a hypothetical old signal as if it were a forward trade.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
import pandas as pd

from .strategy import indicators
from .momentum_paper_test import (
    SOURCE, SLIPPAGE, MAX_HOLD_BARS, _valid_frame, _time,
    _finite, _progress_position,
)

SCHEMA = 1
MAX_DAILY = 12
MAX_HISTORY = 120
MAX_DAILY_LOSS = 20.0
MIN_GAP_BARS = 2
SUPPORTED = frozenset((
    "DRUGA FALA", "EMA TREND", "LIQUIDITY SWEEP",
    "BREAKOUT RETEST", "EMA PULLBACK", "VOLATILITY BREAKOUT",
))


def blank():
    return {"schema": SCHEMA, "last_candle_utc": None, "active": None,
            "closed": [], "started": 0, "opened": 0, "invalidated": 0,
            "gaps": 0, "last_reason": "BRAK NOWEGO SKANU",
            "last_side": "BRAK", "last_setup_utc": None,
            "last_close_utc": None, "attempted_per_utc_day": {},
            "reasons": {}}


def _reason(data, message):
    key = str(message)[:110]
    data["last_reason"] = key
    counts = Counter(data.get("reasons") or {})
    counts[key] += 1
    data["reasons"] = dict(counts.most_common(15))


def _candidate(frame, votes, spread):
    if not isinstance(votes, list):
        return None, "BRAK_GLOSOW_RAW"
    raw = [
        v for v in votes if isinstance(v, dict)
        and v.get("Strategia") in SUPPORTED
        and v.get("Setup OHLC") in ("LONG", "SHORT")
    ]
    if not raw:
        return None, "BRAK_SUROWEGO_LONG_SHORT"
    sides = {v["Setup OHLC"] for v in raw}
    if len(sides) != 1:
        return None, "KONFLIKT_RAW_LONG_SHORT"
    side = sides.pop()
    data = indicators(frame)
    row = data.iloc[-1]
    atr = _finite(row.ATR)
    mid = _finite(row.Close)
    if atr is None or atr <= 0 or mid is None or mid <= 0:
        return None, "BRAK_SPOJNEGO_ATR_CENY"
    if not 0 <= spread <= max(2.0, 0.65 * atr):
        return None, "SPREAD_ZBYT_DUZY_RAW"
    # ATR/last 5 candles, no optimistic hindsight: stops and targets are
    # computed at the setup candle close, *before* the next candle.
    prior = frame.iloc[-6:-1]
    if side == "LONG":
        stop = min(mid - 1.5 * atr, float(prior.Low.min()) - .10 * atr)
        risk = mid - stop
        target = mid + 1.8 * risk
    else:
        stop = max(mid + 1.5 * atr, float(prior.High.max()) + .10 * atr)
        risk = stop - mid
        target = mid - 1.8 * risk
    if not all(isfinite(v) for v in (stop, target, risk)):
        return None, "NIEPOPRAWNE_POZIOMY_RAW"
    if risk <= spread + 2 * SLIPPAGE or risk > 3.5 * atr:
        return None, "RYZYKO_RAW_WOBEC_ATR_KOSZTOW"
    rr = (1.8 * risk - spread - 2 * SLIPPAGE) / (risk + spread + 2 * SLIPPAGE)
    if rr < 1.05:
        return None, "NISKI_RR_RAW_PO_KOSZTACH"
    # Preserve which exact M1 strategies detected the direction;
    # independent MTF decisions are recorded only for comparison.
    methods = list(dict.fromkeys(v["Strategia"] for v in raw))
    accepted = [v["Strategia"] for v in raw
                if v.get("Po filtrze MTF") == side]
    return {
        "side":side, "strategy":"RAW M1 PAPER",
        "methods":methods, "after_mtf":accepted,
        "entry_signal":round(mid,4), "stop":round(stop,4),
        "target":round(target,4), "atr":round(atr,4),
        "spread":round(spread,4), "rr_net_est":round(rr,3),
    }, "RAW_ZATWIERDZONY_"+side


def advance_raw_paper(state, frame, votes, blockers=(), *, spread,
                      source=SOURCE, epic="US500", enabled=True):
    """Advance exactly one new closed M1. No historical replay or broker POST."""
    previous=(state if isinstance(state,dict) and
              state.get("schema")==SCHEMA else blank())
    data={**previous, "closed":list(previous.get("closed") or [])}
    if not enabled:
        data["last_reason"]="RAW_TEST_WYLACZONY"
        return data
    if source!=SOURCE or epic!="US500" or not _valid_frame(frame):
        _reason(data,"NIEWIARYGODNE_ZAMKNIETE_M1_RAW")
        return data
    cost_spread=_finite(spread)
    if cost_spread is None or cost_spread < 0:
        _reason(data,"BRAK_SPREAD_RAW")
        return data
    stamp=frame.index[-1].tz_convert("UTC")
    prior=_time(previous.get("last_candle_utc"))
    if prior is not None and stamp<=prior:
        return data
    data["last_candle_utc"]=stamp.isoformat()
    if prior is not None and stamp-prior!=pd.Timedelta(minutes=1):
        data["gaps"]=int(data.get("gaps",0))+1
        if data.get("active"):
            data["invalidated"]=int(data.get("invalidated",0))+1
        data["active"]=None
        _reason(data,"LUKA_SWIEC_RAW_BEZ_FILL")
        return data

    active=previous.get("active")
    if isinstance(active,dict):
        updated, outcome=_progress_position(active,frame.iloc[-1],stamp)
        if outcome=="INVALID":
            data["invalidated"]=int(data.get("invalidated",0))+1
            data["active"]=None
            data["last_close_utc"]=stamp.isoformat()
            _reason(data,"RAW_FILL_INVALIDATED")
        elif isinstance(outcome,dict):
            if active.get("status")=="PENDING":
                data["opened"]=int(data.get("opened",0))+1
            data["active"]=None
            data["closed"]=(data["closed"]+[outcome])[-MAX_HISTORY:]
            data["last_close_utc"]=stamp.isoformat()
            _reason(data,outcome["status"]+"_RAW")
        else:
            data["active"]=updated
            if active.get("status")=="PENDING" and updated.get("status")=="OPEN":
                data["opened"]=int(data.get("opened",0))+1
            data["last_reason"]="RAW_OPEN_"+str(updated.get("side","?"))
        # One active position, never open another on a closing bar.
        return data

    if blockers:
        _reason(data,"GATES_"+",".join(sorted(str(v) for v in blockers))[:80])
        return data
    last_close=_time(data.get("last_close_utc"))
    if (last_close is not None and
            0 <= (stamp-last_close).total_seconds() < 60*MIN_GAP_BARS):
        _reason(data,"COOLDOWN_RAW_2_MIN")
        return data
    day=stamp.strftime("%Y-%m-%d")
    daily_counts=data.get("attempted_per_utc_day") or {}
    if int(daily_counts.get(day,0))>=MAX_DAILY:
        _reason(data,"MAX_12_RAW_DZIENNIE")
        return data
    loss=sum(float(c.get("pnl_pts") or 0)
             for c in data["closed"] if
             str(c.get("setup_utc",""))[:10]==day)
    if loss<=-MAX_DAILY_LOSS:
        _reason(data,"RAW_DZIENNY_STOP_20_PKT")
        return data

    candidate,reason=_candidate(frame,votes,cost_spread)
    if candidate is None:
        _reason(data,reason)
        return data
    counts={key:value for key,value in daily_counts.items()
            if key>=str((stamp-pd.Timedelta(days=2)).date())}
    counts[day]=int(counts.get(day,0))+1
    data["attempted_per_utc_day"]=counts
    data["started"]=int(data.get("started",0))+1
    data["last_side"]=candidate["side"]
    data["last_setup_utc"]=stamp.isoformat()
    data["active"]={**candidate,"setup_utc":stamp.isoformat(),
                    "status":"PENDING","bars_held":0}
    data["last_reason"]=reason
    return data


def raw_paper_report(state):
    data=state if isinstance(state,dict) and state.get("schema")==SCHEMA else blank()
    closed=[p for p in (data.get("closed") or [])
            if isinstance(p,dict) and p.get("status") in (
                "CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT")
            and _finite(p.get("pnl_pts")) is not None]
    active=data.get("active") if isinstance(data.get("active"),dict) else None
    pnl=sum(float(p["pnl_pts"]) for p in closed)
    wins=sum(float(p["pnl_pts"])>0 for p in closed)
    # Only recorded forward positions; never reconstruct positions from old
    # RAW votes, archived closed candles, or a chart's WATCH markers.
    fields=("status","side","methods","after_mtf","setup_utc",
            "opened_utc","entry_bar_open_utc","entry_signal","entry_mid",
            "entry_exec","stop","target","closed_utc","exit_mid",
            "exit_exec","pnl_pts","r","rr_net_est","bars_held")
    return {
        "status":"FORWARD_ONLY_RAW_M1_SIMULATION",
        "started":int(data.get("started",0)),
        "opened":int(data.get("opened",0)),
        "closed":len(closed),
        "pnl_pts":round(pnl,2),
        "win_rate_pct":round(100*wins/len(closed),1) if closed else None,
        "last_candle_utc":data.get("last_candle_utc"),
        "last_reason":data.get("last_reason"),
        "last_side":data.get("last_side"),
        "last_setup_utc":data.get("last_setup_utc"),
        "gaps":int(data.get("gaps",0)),
        "invalidated":int(data.get("invalidated",0)),
        "active":{k:active.get(k) for k in fields} if active else None,
        "recent":[{k:p.get(k) for k in fields} for p in closed[-80:]],
        "reasons":dict(data.get("reasons") or {}),
        "rules":"RAW sygnał jednej z 6 strategii M1; MTF zapisany do porównania, nie blokuje; globalne GATES obowiązują; następna zamknięta M1 potwierdza OPEN po cenie świecy + koszty",
        "no_broker_orders":True,
        "research_only":True,
    }
