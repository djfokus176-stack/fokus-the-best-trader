"""Redacted counts from the existing durable virtual-trading checkpoint.

The *public* GitHub watchdog logs may contain these COUNTS, but never order
prices, trade identifiers, positions, credentials, full checkpoint or P&L.
An OPEN requires the worker's saved opened_utc; PENDING is never an entry.
AUTO origin is checked with the same attribution as the owner terminal.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .auto_sim_journal import auto_sim_journal, _utc
from .paper_method_labels import method_attribution
from .worker_signal_diagnostics import verified_auto_wait_diagnosis

COMPLETE = ("CLOSED_TP", "CLOSED_SL", "CLOSED_TIMEOUT")


def _int(value):
    return value if type(value) is int and 0 <= value <= 1_000_000 else None


def _time(value):
    t=_utc(value)
    return t.isoformat(timespec="seconds") if t is not None else "NONE"


def _safe_feed_issue(meta):
    """Whitelist a cause from the last worker message; never log provider text."""
    summary=str(meta.get("last_scan_summary") or "")[:350]
    if " / DATA_STALE / " not in summary:
        if " / NO_FEED / " in summary:
            return "NO_M1_FEED"
        return "NONE"
    reasons=(
        ("Bieżący spread:", "FORMING_SPREAD_TOO_WIDE"),
        ("Spread zamkniętej świecy:", "CLOSED_SPREAD_TOO_WIDE"),
        ("Dane przestarzałe", "OLD_CANDLES"),
        ("WYGASŁY ODCZYT", "OLD_CANDLES"),
        ("Wykryto duże luki", "HOLES_IN_OHLC"),
        ("DANE_WADLIWE", "CORRUPT_OHLC"),
        ("Za mało poprawnych świec", "INSUFFICIENT_OHLC"),
        ("Świece z przyszłości", "CLOCK_MISMATCH"),
        ("Brak świecy następującej", "MISSING_FOLLOWING_CANDLE"),
        ("Puste OHLC", "EMPTY_OHLC"),
    )
    for needle,code in reasons:
        if needle in summary:
            return code
    return "STALE_OTHER_OR_TRUNCATED"


def read_only_archive_counts(payload, *, now=None):
    """Return counts only, never expose prices, IDs, funds, or private keys."""
    current=now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("UTC-aware now is required")
    current=current.astimezone(timezone.utc)
    today=current.date()
    if not isinstance(payload,dict):
        return {"status":"NO_CHECKPOINT"}
    tab=payload.get("tables")
    raw=tab.get("paper_positions_v3") if isinstance(tab,dict) else None
    if not isinstance(raw,list):
        return {"status":"NO_LEDGER"}
    journal=auto_sim_journal(payload)
    if not journal["known"]:
        return {"status":"NO_VERIFIED_AUTO_LEDGER"}
    result={
        "status":"VERIFIED_LEDGER",
        "ledger_rows":len(raw),
        "auto_opened":journal["opened"],
        "auto_closed":journal["closed"],
        "auto_pending":int(journal["pending"] is not None),
        "auto_active":int(journal["active"] is not None),
        "auto_invalidated":journal["invalidated"],
        "auto_incomplete":journal["incomplete"],
        "auto_long_opened":0,"auto_short_opened":0,
        "auto_closed_tp":0,"auto_closed_sl":0,"auto_closed_timeout":0,
        "auto_opened_today_utc":0,"auto_closed_today_utc":0,
        "last_auto_open_utc":"NONE","last_auto_close_utc":"NONE",
        "last_auto_close_side":"NONE",
    }
    ids=set()
    last_open=None
    last_close=None
    for p in raw:
        if (not isinstance(p,dict) or p.get("side") not in ("LONG","SHORT")
                or p.get("epic")!="US500"
                or p.get("source")!="Capital.com DEMO REST"):
            continue
        ident=p.get("trade_id")
        if not isinstance(ident,str) or not ident or ident in ids:
            continue
        ids.add(ident)
        if not method_attribution(p)["label"].startswith("AUTO → "):
            continue
        state=p.get("status")
        if state not in ("OPEN",)+COMPLETE:
            continue
        opened=_utc(p.get("opened_utc"))
        if opened is None or p.get("entry_mid") is None:
            continue
        if state in COMPLETE:
            closed=_utc(p.get("closed_utc"))
            if (closed is None or closed<opened or
                    p.get("exit_mid") is None or p.get("pnl_pts") is None):
                continue
        else:
            closed=None
        result["auto_"+p["side"].lower()+"_opened"]+=1
        if opened.date()==today:
            result["auto_opened_today_utc"]+=1
        if last_open is None or opened>last_open:
            last_open=opened
        if closed is not None:
            key={"CLOSED_TP":"auto_closed_tp",
                 "CLOSED_SL":"auto_closed_sl",
                 "CLOSED_TIMEOUT":"auto_closed_timeout"}[state]
            result[key]+=1
            if closed.date()==today:
                result["auto_closed_today_utc"]+=1
            if last_close is None or closed>last_close:
                last_close=closed
                result["last_auto_close_side"]=p["side"]
    result["last_auto_open_utc"]=last_open.isoformat(timespec="seconds") if last_open else "NONE"
    result["last_auto_close_utc"]=last_close.isoformat(timespec="seconds") if last_close else "NONE"
    for name,key in (("momentum_paper_test_report","momentum"),
                     ("raw_m1_forward_paper_report","raw")):
        row=payload.get(name)
        if isinstance(row,dict):
            for field in ("started","opened","closed"):
                parsed=_int(row.get(field))
                result[key+"_"+field]=parsed if parsed is not None else "UNKNOWN"
        else:
            result[key+"_started"]="UNKNOWN"
            result[key+"_opened"]="UNKNOWN"
            result[key+"_closed"]="UNKNOWN"
    # RAW is a separate experimental ledger: an OPEN can be subsequently
    # invalidated after a missing M1 candle. Never imply that every OPEN
    # has a CLOSED P&L, or that those research positions were AUTO trades.
    raw_report=payload.get("raw_m1_forward_paper_report")
    for field in ("closed_total","invalidated_after_open",
                  "invalidated_before_open","unreconciled_historical_open",
                  "active_open_now","gaps"):
        value=raw_report.get(field) if isinstance(raw_report,dict) else None
        checked=_int(value)
        result["raw_"+field]=(checked if checked is not None else "UNKNOWN")
    report=payload.get("periodic_audit_report")
    if isinstance(report,dict):
        result["periodic_archive_status"]=str(report.get("status","UNKNOWN"))[:48]
        stored=_int(report.get("stored_trades"))
        result["periodic_archive_stored"]=stored if stored is not None else "UNKNOWN"
    else:
        result["periodic_archive_status"]="UNKNOWN"
        result["periodic_archive_stored"]="UNKNOWN"
    # Display only safe enums from the last actual scan. A healthy worker
    # heartbeat (OK) is not proof that the strategy approved an entry.
    import re
    meta=payload.get("meta") if isinstance(payload.get("meta"),dict) else {}
    flag=meta.get("auto_virtual_daily_brake_enabled")
    result["auto_daily_brake"]=(
        "ON" if flag is True else "OFF" if flag is False else "UNKNOWN")
    result["feed_issue"]=_safe_feed_issue(meta)
    # A non-secret 12-hex source digest confirms which worker code produced
    # the checkpoint. Do NOT expose environment, git auth or full file text.
    fingerprint=meta.get("worker_source_fingerprint")
    result["worker_code"]=(fingerprint if isinstance(fingerprint,str)
        and re.fullmatch(r"[0-9a-f]{12}",fingerprint) else "UNKNOWN")
    summary=str(meta.get("last_scan_summary") or "")[:350]
    match=re.search(r"(?:^| / )(LONG|SHORT|WAIT)(?= /|$)",summary)
    result["last_decision"]=match.group(1) if match else "UNKNOWN"
    queued=re.search(r"(?:^| / )QUEUE=(YES|NO)(?= /|$)",summary)
    result["last_queued"]=queued.group(1) if queued else "UNKNOWN"
    gates=re.search(r"(?:^| / )GATES=([A-Z0-9_,]+)(?= /|$)",summary)
    # Only known self-generated codes, not arbitrary provider messages.
    result["last_gates"]=(gates.group(1) if gates and
                          len(gates.group(1))<=48 else "UNKNOWN")
    # The six-strategy diagnostic is valid only when it belongs to this
    # exact fresh, timestamp-matched scan (never reuse yesterday's votes).
    result.update(verified_auto_wait_diagnosis(payload,now=current))
    return result


def redacted_archive_log_line(payload, *, now=None):
    """Log only bounded, non-secret audit fields in a stable order."""
    result=read_only_archive_counts(payload,now=now)
    parts=[]
    for key,value in result.items():
        text=str(value)
        if (len(key)>42 or len(text)>60
                or not all(ch.isalnum() or ch in "_-:+." for ch in text)):
            text="UNKNOWN"
        parts.append(key.upper()+"="+text)
    return "FOKUS_ARCHIVE / "+" / ".join(parts)
