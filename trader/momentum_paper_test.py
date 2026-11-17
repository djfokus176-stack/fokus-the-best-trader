"""Independent momentum PAPER TEST ledger, NOT the six-strategy AUTO engine.

A user-requested experimental source of LONG/SHORT approvals from closed
M1 observations, with conservative next-bar synthetic fills and exits.
No broker orders, no Supabase schema changes, no mutation of PAPER v3.
Must be clearly labeled TEST and tracked independently of production PAPER.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
import pandas as pd

from .early_watch import evaluate_early_watch
from .strategy import indicators

VERSION = 1
SOURCE = "Capital.com DEMO REST"
MAX_HISTORY = 100
MAX_TRADES_PER_UTC_DAY = 8
MAX_DAILY_LOSS_PTS = 15.0
MAX_HOLD_BARS = 20
COOLDOWN_M1 = 5
SLIPPAGE = .25
MIN_SCORE = 5
TEST_MTF = ("MINUTE_5", "MINUTE_15")
EMA_NAMES = ("EMA TREND", "EMA PULLBACK")


def blank():
    return {"schema": VERSION, "last_candle_utc": None,
            "active": None, "closed": [], "opened": 0,
            "started": 0, "invalidated": 0, "gaps": 0,
            "last_reason": "NIE URUCHOMIONO SKANU",
            "last_candidate": "WAIT", "last_setup_utc": None,
            "last_close_utc": None, "last_side": "BRAK",
            "reasons": {}}


def _time(stamp):
    try:
        result = pd.Timestamp(stamp)
    except (ValueError, TypeError, OverflowError):
        return None
    if pd.isna(result) or result.tzinfo is None:
        return None
    return result.tz_convert("UTC")


def _finite(num):
    try:
        n = float(num)
    except (ValueError, TypeError, OverflowError):
        return None
    return n if isfinite(n) else None


def _valid_frame(frame):
    if (not isinstance(frame, pd.DataFrame) or len(frame) < 85
            or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None or not frame.index.is_monotonic_increasing
            or frame.index.has_duplicates
            or not {"Open", "High", "Low", "Close"}.issubset(frame.columns)):
        return False
    recent = frame.iloc[-10:]
    if any((recent.index[i] - recent.index[i-1]).total_seconds() != 60
           for i in range(1, len(recent))):
        return False
    for col in ("Open", "High", "Low", "Close"):
        if not all(isfinite(float(v)) for v in recent[col]):
            return False
    for bar in recent.itertuples():
        if (bar.Low > min(bar.Open, bar.Close)
                or bar.High < max(bar.Open, bar.Close)
                or bar.Low > bar.High):
            return False
    return True


def _log_reason(state, reason):
    state["last_reason"] = reason[:140]
    reasons = dict(state.get("reasons") or {})
    reasons[reason[:80]] = int(reasons.get(reason[:80], 0)) + 1
    state["reasons"] = dict(Counter(reasons).most_common(15))


def _test_candidate(frame, progress, views, spread):
    """Only high-score momentum + a 2/3 EMA context + M5/M15 protection.

    Unlike the strict production MTF, H1 direction does not veto this
    *independent* experiment. M5 must agree and M15 must not oppose.
    All global worker data/news/risk guards are enforced by the caller.
    """
    watch = evaluate_early_watch(frame)
    side = watch.side
    if side not in ("LONG", "SHORT") or watch.score < MIN_SCORE:
        return None, "BRAK_MOMENTUM_MINIMUM_5_6"
    if watch.countertrend:
        return None, "MOMENTUM_PRZECIW_EMA9_21"
    if not isinstance(progress, list):
        return None, "BRAK_ETAPOW_STRATEGII"
    supported = [
        p for p in progress if isinstance(p, dict)
        and p.get("strategy") in EMA_NAMES and p.get("side") == side
        and p.get("stage") in (2, 3)
    ]
    if not supported:
        return None, "BRAK_EMA_ETAPU_2_3_Z_TYM_KIERUNKIEM"
    if not isinstance(views, (list, tuple)):
        return None, "BRAK_MTF"
    view_by_tf = {getattr(v, "timeframe", None): v for v in views}
    if not all(tf in view_by_tf and getattr(view_by_tf[tf], "ready", False)
               for tf in TEST_MTF):
        return None, "BRAK_ZWERYFIKOWANYCH_M5_M15"
    want = "UP" if side == "LONG" else "DOWN"
    opposite = "DOWN" if side == "LONG" else "UP"
    if getattr(view_by_tf["MINUTE_5"], "trend", None) != want:
        return None, "M5_NIE_POTWIERDZA_" + side
    if getattr(view_by_tf["MINUTE_15"], "trend", None) == opposite:
        return None, "M15_PRZECIWNY_" + side
    data = indicators(frame)
    a = data.iloc[-1]
    atr = _finite(a.ATR)
    mid = _finite(a.Close)
    if atr is None or atr <= 0 or mid is None:
        return None, "BRAK_ATR_LUB_CENY"
    if spread > max(1.2, .4*atr):
        return None, "SPREAD_ZBYT_DUZY_WOBEC_ATR"
    latest = frame.iloc[-6:-1]
    if side == "LONG":
        stop = min(mid-2.0*atr, float(latest.Low.min())-.12*atr)
        risk = mid-stop
        target = mid + 2*risk
    else:
        stop = max(mid+2.0*atr, float(latest.High.max())+.12*atr)
        risk = stop-mid
        target = mid - 2*risk
    if not all(isfinite(v) for v in (stop, risk, target)):
        return None, "BLAD_GEOMETRII"
    if risk <= 1.5*spread or risk > 3*atr:
        return None, "RYZYKO_NIEPROPORCJONALNE_DO_SPREAD_ATR"
    # Use total round-trip spread plus slippage on BOTH sides.
    net_rr = (2*risk-spread-2*SLIPPAGE) / (risk+spread+2*SLIPPAGE)
    if net_rr < 1.20:
        return None, "RR_PO_KOSZTACH_PONIZEJ_1_20"
    return {
        "side": side, "score": watch.score,
        "strategy": "MOMENTUM_M1_TEST",
        "confirmation": ",".join(p["strategy"] for p in supported),
        "entry_signal": round(mid, 3), "stop": round(stop, 3),
        "target": round(target, 3), "atr": round(atr, 3),
        "spread": round(spread, 4), "rr_net_est": round(net_rr, 3),
    }, "TEST_SETUP_ZATWIERDZONY_" + side


def _progress_position(position, candle, stamp):
    """Next closed M1 reveals hypothetical entry at that bar's OPEN."""
    cur = dict(position)
    op,hi,lo,cl = (float(candle.Open), float(candle.High),
                   float(candle.Low), float(candle.Close))
    if not all(isfinite(x) for x in (op,hi,lo,cl)):
        return None, "INVALID"
    if not (lo<=min(op,cl)<=max(op,cl)<=hi):
        return None, "INVALID"
    side = cur["side"]
    if cur["status"] == "PENDING":
        if _time(cur["setup_utc"])+pd.Timedelta(minutes=1) != stamp:
            return None, "INVALID"
        if not (cur["stop"]<op<cur["target"] if side=="LONG"
                else cur["target"]<op<cur["stop"]):
            return None, "INVALID"
        entry_cost = cur["spread"]/2+SLIPPAGE
        cur["entry_mid"]=op
        cur["entry_exec"]=op+(entry_cost if side=="LONG" else -entry_cost)
        cur["opened_utc"]=stamp.isoformat()
        cur["status"]="OPEN"
        cur["bars_held"]=0
    cur["bars_held"]+=1
    if side=="LONG":
        hit_sl=lo<=cur["stop"]
        hit_tp=hi>=cur["target"]
    else:
        hit_sl=hi>=cur["stop"]
        hit_tp=lo<=cur["target"]
    if hit_sl:
        closed_at=(min(cur["stop"],op) if side=="LONG" else
                   max(cur["stop"],op))
        close_status="CLOSED_SL"
    elif hit_tp:
        closed_at=cur["target"]
        close_status="CLOSED_TP"
    elif cur["bars_held"] >= MAX_HOLD_BARS:
        closed_at=cl
        close_status="CLOSED_TIMEOUT"
    else:
        return cur, None
    cost=cur["spread"]/2+SLIPPAGE
    exit_exec=closed_at+(-cost if side=="LONG" else cost)
    pnl = (exit_exec-cur["entry_exec"] if side=="LONG"
           else cur["entry_exec"]-exit_exec)
    r_mid=abs(cur["entry_mid"]-cur["stop"])
    if not isfinite(pnl) or r_mid<=0:
        return None, "INVALID"
    cur.update(status=close_status,closed_utc=stamp.isoformat(),
               exit_exec=round(exit_exec,4),exit_mid=closed_at,
               pnl_pts=round(pnl,3),r=round(pnl/r_mid,4))
    return None, cur


def advance_momentum_paper_test(state, frame, progress, views, blockers=(),
                                *, spread, source=SOURCE, epic="US500",
                                enabled=True):
    """One forward-only independent candidate/position lane per US500 DEMO.

    Scans historical gap/data state independently, but enforces the existing
    global blockers before NEW test entries. Positions already active may be
    settled while blocking new entries. A disconnect invalidates (not fills).
    """
    prior = state if isinstance(state,dict) and state.get("schema")==VERSION else blank()
    data = {**prior}
    data["closed"] = list(prior.get("closed") or [])
    if not enabled:
        data["last_reason"]="TEST_WYLACZONY"
        return data
    if source!=SOURCE or epic!="US500" or not _valid_frame(frame):
        data["last_reason"]="NIEWIARYGODNE_ZAMKNIETE_M1"
        return data
    spread_value=_finite(spread)
    if spread_value is None or spread_value<0:
        data["last_reason"]="SPREAD_NIEDOSTEPNY"
        return data
    stamp = frame.index[-1].tz_convert("UTC")
    old = _time(prior.get("last_candle_utc")) if prior.get("last_candle_utc") else None
    if old is not None and stamp<=old:
        return data
    data["last_candle_utc"]=stamp.isoformat()
    if old is not None and stamp-old!=pd.Timedelta(minutes=1):
        data["gaps"]=int(data.get("gaps",0))+1
        if data.get("active"):
            data["invalidated"]=int(data.get("invalidated",0))+1
        data["active"]=None
        _log_reason(data,"LUKA_M1_POMIJAM_NOWE_WEJSCIE")
        return data
    active=prior.get("active")
    if active:
        updated,outcome=_progress_position(active,frame.iloc[-1],stamp)
        if outcome=="INVALID":
            data["invalidated"]=int(data.get("invalidated",0))+1
            data["active"]=None
            data["last_close_utc"]=stamp.isoformat()
            _log_reason(data,"NIEWAZNY_FILL_LUB_GEOMETRIA")
        elif isinstance(outcome,dict):
            data["active"]=None
            data["closed"]=(data["closed"]+[outcome])[-MAX_HISTORY:]
            data["last_close_utc"]=stamp.isoformat()
            if active.get("status")=="PENDING":
                data["opened"]=int(data.get("opened",0))+1
            _log_reason(data,outcome["status"])
        else:
            data["active"]=updated
            if active.get("status")=="PENDING" and updated.get("status")=="OPEN":
                data["opened"]=int(data.get("opened",0))+1
            data["last_reason"]="TEST_OPEN_"+updated["side"]
            return data
        # Prevent immediate churn after an exit/invalidated setup.
        return data
    if blockers:
        _log_reason(data,"GLOBAL_GATES_"+",".join(sorted(str(x) for x in blockers))[:80])
        return data
    closed_at=_time(data.get("last_close_utc")) if data.get("last_close_utc") else None
    if closed_at and 0 <= (stamp-closed_at).total_seconds() < 60*COOLDOWN_M1:
        _log_reason(data,"COOLDOWN_"+str(COOLDOWN_M1)+"_MIN")
        return data
    # Bounded daily exposure in simulated experiments. Historical start
    # is stored for each setup. No time assumptions from the browser.
    current_day=stamp.strftime("%Y-%m-%d")
    starts_today=sum(1 for p in data["closed"]
                     if str(p.get("setup_utc",""))[:10]==current_day)
    if data.get("active") and str(data["active"].get("setup_utc",""))[:10]==current_day:
        starts_today+=1
    if starts_today >= MAX_TRADES_PER_UTC_DAY:
        _log_reason(data,"DZIENNY_LIMIT_TEST_8")
        return data
    daily_pnl=sum(float(p.get("pnl_pts") or 0)
                  for p in data["closed"]
                  if str(p.get("setup_utc",""))[:10]==current_day)
    if daily_pnl<=-MAX_DAILY_LOSS_PTS:
        _log_reason(data,"DZIENNY_STOP_TEST_15_PKT")
        return data
    candidate,reason=_test_candidate(frame,progress,views,spread_value)
    data["last_candidate"]=candidate["side"] if candidate else "WAIT"
    if candidate is None:
        _log_reason(data,reason)
        return data
    data["started"]=int(data.get("started",0))+1
    data["last_setup_utc"]=stamp.isoformat()
    data["last_side"]=candidate["side"]
    data["active"]={
        **candidate,"setup_utc":stamp.isoformat(),
        "status":"PENDING","bars_held":0,
    }
    data["last_reason"]=reason
    return data


def momentum_paper_test_report(state):
    data=state if isinstance(state,dict) and state.get("schema")==VERSION else blank()
    rows=[r for r in data.get("closed",[]) if isinstance(r,dict)
          and r.get("status") in ("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")
          and _finite(r.get("pnl_pts")) is not None]
    total=sum(float(r["pnl_pts"]) for r in rows)
    wins=sum(float(r["pnl_pts"])>0 for r in rows)
    position=data.get("active")
    return {
        "status":"FORWARD_PAPER_TEST_NOT_LIVE",
        "closed":len(rows),"opened":int(data.get("opened",0)),
        "started":int(data.get("started",0)),
        "pending":bool(position and position.get("status")=="PENDING"),
        "active":({k:position.get(k) for k in (
            "side","status","setup_utc","opened_utc","entry_signal",
            "entry_mid","stop","target","score","confirmation",
            "rr_net_est")} if isinstance(position,dict) else None),
        "pnl_pts":round(total,2),
        "win_rate_pct":round(100*wins/len(rows),1) if rows else None,
        "last_candle_utc":data.get("last_candle_utc"),
        "last_reason":str(data.get("last_reason") or "BRAK")[:140],
        "last_candidate":str(data.get("last_candidate") or "WAIT"),
        "last_side":str(data.get("last_side") or "BRAK"),
        "last_setup_utc":data.get("last_setup_utc"),
        "gaps":int(data.get("gaps",0)),
        "invalidated":int(data.get("invalidated",0)),
        "recent": [{
            "side":r.get("side"),"status":r.get("status"),
            "setup_utc":r.get("setup_utc"),"opened_utc":r.get("opened_utc"),
            "closed_utc":r.get("closed_utc"),"pnl_pts":r.get("pnl_pts"),
            "r":r.get("r"),"score":r.get("score"),
        } for r in rows[-12:][::-1]],
        "minimum_closed_for_exploration":100,
        "rules":"M1 momentum >=5/6, EMA 2/3, M5 zgodny, M15 nieprzeciwny, globalne bramki, RR i koszty",
        "no_real_orders":True,
    }
