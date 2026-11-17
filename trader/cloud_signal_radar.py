"""Explain the actual six-strategy worker audit to the Streamlit owner.

Read-only; no strategy calculations, external calls, trade creation, or
synthetic LONG/SHORT/entry/SL/TP. Works on persisted checkpoint data only.
"""
from __future__ import annotations

from datetime import datetime, timezone

AUTO_MODE = "AUTO — 6 STRATEGII"
EXPECTED_SOURCE = "Capital.com DEMO REST"
DIRECTIONS = {"LONG", "SHORT", "WAIT"}
OBSERVATION_SIDES = {"LONG", "SHORT", "BRAK", "NIEJEDNOZNACZNY"}


def _utc(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo else None


def _limited(value, count=180):
    return str(value if value is not None else "BRAK")[:count]


def worker_signal_radar(payload, *, now=None):
    """Return only grounded decisions and progress from the CURRENT worker scan.

    A checkpoint can be recently written while its last_vote_audit belongs to
    a previous candle. Check scan SUMMARY and audit candle IDs against each
    other; otherwise flag the whole radar as historical/unknown.
    """
    empty = {
        "current": False, "reason": "BRAK_BIEŻĄCEGO_AUDYTU",
        "rows": [], "raw_long": 0, "raw_short": 0,
        "mtf_long": 0, "mtf_short": 0,
        "veto": 0, "conflict": False,
        "watch": {"side": "WAIT", "score": None, "reason": "BRAK"},
        "candle_utc": None, "scan_utc": None, "is_trade_instruction": False,
    }
    if not isinstance(payload, dict):
        return empty
    meta = payload.get("meta")
    audit = payload.get("last_vote_audit")
    if not isinstance(meta, dict) or not isinstance(audit, dict):
        return empty
    if (meta.get("source") != EXPECTED_SOURCE or meta.get("epic") != "US500"
            or meta.get("strategy") != AUTO_MODE
            or audit.get("source") != EXPECTED_SOURCE or audit.get("epic") != "US500"
            or audit.get("mode") != AUTO_MODE):
        return {**empty, "reason": "NIEZGODNE_ŹRÓDŁO_LUB_TRYB"}

    clock = _utc(now) if now is not None else datetime.now(timezone.utc)
    stamped = _utc(meta.get("last_scan_utc"))
    closed = _utc(audit.get("candle_utc"))
    if clock is None or stamped is None or closed is None:
        return {**empty, "reason": "BRAK_ZWERYFIKOWANYCH_CZASÓW"}
    age = (clock - stamped).total_seconds()
    candle_age = (clock - closed).total_seconds()
    if not (0 <= age <= 180 and 0 <= candle_age <= 300):
        return {**empty, "reason": "STARY_SKAN_LUB_ŚWIECA",
                "scan_utc": stamped.isoformat(),
                "candle_utc": closed.isoformat()}
    # The checkpoint may be NEW, yet the last votes are old after DATA_STALE.
    # Such votes are NEVER shown as a current recommendation.
    summary = str(meta.get("last_scan_summary") or "")
    if not summary.startswith(str(audit.get("candle_utc")) + " / "):
        return {**empty, "reason": "GŁOSY_Z_POPRZEDNIEGO_SKANU",
                "scan_utc": stamped.isoformat(),
                "candle_utc": closed.isoformat()}

    votes = audit.get("rows")
    if not isinstance(votes, list) or len(votes) != 6:
        return {**empty, "reason": "BRAK_SZEŚCIU_GŁOSÓW"}
    stage_rows = audit.get("progress")
    if not isinstance(stage_rows, list):
        stage_rows = []
    steps = {p.get("strategy"): p for p in stage_rows
             if isinstance(p, dict) and isinstance(p.get("strategy"), str)}
    output = []
    for v in votes:
        if not isinstance(v, dict) or not isinstance(v.get("strategy"), str):
            return {**empty, "reason": "USZKODZONY_REJESTR_GŁOSÓW"}
        raw = v.get("raw") if v.get("raw") in DIRECTIONS else "WAIT"
        after = v.get("after_mtf") if v.get("after_mtf") in DIRECTIONS else "WAIT"
        progress = steps.get(v["strategy"], {})
        try:
            stage = int(progress.get("stage", -1))
        except (ValueError, TypeError, OverflowError):
            stage = -1
        if stage not in (0, 1, 2, 3):
            stage = None
        side = (progress.get("side")
                if progress.get("side") in OBSERVATION_SIDES else "BRAK")
        criteria = progress.get("criteria")
        missing = "Brak danych o etapach"
        if isinstance(criteria, list):
            for check in criteria:
                if isinstance(check, dict) and check.get("ok") is False:
                    missing = _limited(check.get("name"), 105)
                    break
            else:
                missing = "Etapy spełnione; sprawdź bramki"
        reason = _limited(v.get("reason") or progress.get("reason"), 190)
        output.append({
            "Strategia": _limited(v["strategy"], 75),
            "Etap": f"{stage}/3" if stage is not None else "BRAK",
            "Obserwuj": side,
            "Setup OHLC": raw,
            "Po MTF": after,
            "Brakuje": missing,
            "Dlaczego": reason,
        })

    watch = audit.get("watch")
    if not isinstance(watch, dict):
        watch = {}
    side = watch.get("side") if watch.get("side") in DIRECTIONS else "WAIT"
    try:
        score = int(watch.get("score", -1))
    except (TypeError, ValueError, OverflowError):
        score = -1
    if not 0 <= score <= 6:
        score = None
    raw_long = sum(v["Setup OHLC"] == "LONG" for v in output)
    raw_short = sum(v["Setup OHLC"] == "SHORT" for v in output)
    mtf_long = sum(v["Po MTF"] == "LONG" for v in output)
    mtf_short = sum(v["Po MTF"] == "SHORT" for v in output)
    return {
        **empty, "current": True, "reason": "OK",
        "rows": output,
        "raw_long": raw_long, "raw_short": raw_short,
        "mtf_long": mtf_long, "mtf_short": mtf_short,
        "veto": sum(v["Setup OHLC"] in ("LONG", "SHORT")
                    and v["Po MTF"] == "WAIT" for v in output),
        "conflict": bool(raw_long and raw_short),
        "watch": {"side": side, "score": score,
                  "reason": _limited(watch.get("reason"), 240)},
        "candle_utc": closed.isoformat(), "scan_utc": stamped.isoformat(),
    }
