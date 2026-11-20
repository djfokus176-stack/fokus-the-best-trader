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

COMPLETE = ("CLOSED_TP", "CLOSED_SL", "CLOSED_TIMEOUT")


def _int(value):
    return value if type(value) is int and 0 <= value <= 1_000_000 else None


def _time(value):
    t=_utc(value)
    return t.isoformat(timespec="seconds") if t is not None else "NONE"


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
    report=payload.get("periodic_audit_report")
    if isinstance(report,dict):
        result["periodic_archive_status"]=str(report.get("status","UNKNOWN"))[:48]
        stored=_int(report.get("stored_trades"))
        result["periodic_archive_stored"]=stored if stored is not None else "UNKNOWN"
    else:
        result["periodic_archive_status"]="UNKNOWN"
        result["periodic_archive_stored"]="UNKNOWN"
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
