"""Self-correcting SHADOW forecast audit on verified CLOSED Capital DEMO bars.

No orders, no effect on AUTO/MTF/PAPER gates, and no fabricated certainty.
Each prediction is persisted BEFORE its future bar exists; the subsequent
scan resolves it only when the very next timestamp is observed.
"""
from __future__ import annotations

from datetime import timedelta
import math

MODELS = ("NAIVE", "MOMENTUM", "MEAN_REVERSION")
MAX_HISTORY = 240


def _candidates(frame):
    closes = [float(v) for v in frame["Close"].tail(6)]
    if len(closes) < 6 or not all(math.isfinite(v) and v > 0 for v in closes):
        raise ValueError("Insufficient finite closed prices")
    last = closes[-1]
    changes = [b-a for a, b in zip(closes[:-1], closes[1:])]
    average = sum(changes[-4:])/4
    scale = max(0.01, sum(abs(v) for v in changes[-5:])/5)
    bounded = max(-scale, min(scale, average))
    return {"NAIVE":last,
            "MOMENTUM":last+0.35*bounded,
            "MEAN_REVERSION":last-0.25*bounded}


def _select(history):
    """Choose lowest prior MAE, never based on a future or same-bar outcome."""
    rows = list(history)[-90:]
    if len(rows) < 30:
        return "NAIVE"
    means = {}
    for model in MODELS:
        errors = [float(r["errors"][model]) for r in rows
                  if isinstance(r.get("errors"), dict) and model in r["errors"]]
        means[model] = sum(errors)/len(errors) if len(errors) >= 25 else float("inf")
    return min(MODELS, key=lambda name:(means[name], MODELS.index(name)))


def forecast_metrics(state):
    rows = list(state.get("resolved") or [])
    n = len(rows)
    if not n:
        return {"observations":0, "status":"BRAK WERYFIKACJI",
                "model":"NAIVE", "mae":None, "baseline_mae":None,
                "direction_accuracy_pct":None, "beat_baseline":False}
    mean = lambda values: sum(values)/len(values)
    errors = [float(r["abs_error"]) for r in rows]
    baseline = [float(r["errors"]["NAIVE"]) for r in rows]
    directional = [bool(r["direction_hit"]) for r in rows]
    mae = mean(errors)
    baseline_mae = mean(baseline)
    # No invented 80-95% confidence: a short noisy win streak proves nothing.
    status = "BADAWCZA / BRAK DOWODU"
    if n >= 100:
        status = "WERYFIKACJA OOS W TOKU"
    return {"observations":n, "status":status,
            "model":state.get("last_model", "NAIVE"),
            "mae":round(mae,5),
            "baseline_mae":round(baseline_mae,5),
            "direction_accuracy_pct":round(100*mean(directional),2),
            "beat_baseline":n >= 100 and mae < baseline_mae,
            "missed_candles":int(state.get("missed_candles",0))}


def update_forecast(state, snapshot):
    """Pure state transition: one next-bar forecast per verified closed minute.

    A missed timestamp invalidates scoring rather than silently using
    a later bar. Duplicate scans cannot add predictions or outcomes.
    """
    if not getattr(snapshot, "good", False):
        return dict(state or {})
    frame = snapshot.frame
    if frame is None or len(frame) < 6 or getattr(snapshot, "confirmed_utc", None) is None:
        return dict(state or {})
    from .market import PERIOD
    tf = str(snapshot.resolution)
    if tf not in PERIOD:
        return dict(state or {})
    stamp = snapshot.confirmed_utc.isoformat()
    close = float(frame["Close"].iloc[-1])
    if not math.isfinite(close) or close <= 0:
        return dict(state or {})
    work = dict(state or {})
    scope = {"epic":str(snapshot.epic), "source":str(snapshot.source), "timeframe":tf}
    if work.get("scope") != scope:
        work = {"scope":scope, "resolved":[], "missed_candles":0}
    pending = work.get("pending")
    if isinstance(pending,dict):
        if pending.get("at_utc") == stamp:
            return work
        from datetime import datetime
        at = datetime.fromisoformat(str(pending["at_utc"]))
        now = datetime.fromisoformat(stamp)
        target = at + timedelta(seconds=PERIOD[tf])
        if now == target:
            predicted = float(pending["predicted"])
            previous = float(pending["previous_close"])
            predicted_change = predicted-previous
            actual_change = close-previous
            direction_hit = (predicted_change*actual_change > 0
                             if abs(predicted_change)>1e-12
                             else abs(actual_change)<=1e-12)
            by_model = {k:abs(close-float(v))
                        for k,v in pending["candidates"].items()}
            event = {"at_utc":pending["at_utc"],"target_utc":stamp,
                     "model":pending["model"],"previous_close":previous,
                     "predicted":predicted,"actual":close,
                     "abs_error":abs(close-predicted),
                     "direction_hit":bool(direction_hit),"errors":by_model}
            work["resolved"] = (list(work.get("resolved") or [])+[event])[-MAX_HISTORY:]
        elif now>target:
            work["missed_candles"]=int(work.get("missed_candles",0))+1
        elif now<at:
            # Clock moved backwards; never score it.
            work["missed_candles"]=int(work.get("missed_candles",0))+1
        else:
            return work
    estimates = _candidates(frame)
    chosen = _select(work.get("resolved") or [])
    work["pending"]={"at_utc":stamp, "previous_close":close, "model":chosen,
                     "predicted":round(float(estimates[chosen]),5),
                     "candidates":{k:round(float(v),5) for k,v in estimates.items()}}
    work["last_model"]=chosen
    work["metrics"]=forecast_metrics(work)
    return work
