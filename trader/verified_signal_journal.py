"""Auditable PAPER v3 OPEN/CLOSE signals, not presumed sound delivery.

Read-only: every row is backed by a persisted paper_events_v3 entry and a
matching source/epic position. The model entry, closed-bar confirmation,
and worker event time are different clocks. Browser audio attempts are
session-local and are NEVER evidence that the user heard an alert.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .paper_method_labels import method_attribution
from .trade_time_labels import in_poland, aware

SOURCE="Capital.com DEMO REST"
EVENT_KINDS={
    "PAPER_OPEN":"OTWARCIE",
    "PAPER_CLOSE_TP":"ZAMKNIĘCIE TP",
    "PAPER_CLOSE_SL":"ZAMKNIĘCIE SL",
    "PAPER_TIMEOUT":"ZAMKNIĘCIE CZAS",
}
CLOSE_STATUS={
    "PAPER_CLOSE_TP":"CLOSED_TP",
    "PAPER_CLOSE_SL":"CLOSED_SL",
    "PAPER_TIMEOUT":"CLOSED_TIMEOUT",
}
MAX_EVENTS=80


def verified_signal_rows(payload,*,limit=30):
    """Only real persisted worker events; no watch/PENDING/RAW pretend OPEN."""
    if not isinstance(payload,dict):
        return []
    meta=payload.get("meta")
    tables=payload.get("tables")
    if not isinstance(meta,dict) or not isinstance(tables,dict):
        return []
    if meta.get("source")!=SOURCE or meta.get("epic")!="US500":
        return []
    positions=tables.get("paper_positions_v3")
    events=tables.get("paper_events_v3")
    if not isinstance(positions,list) or not isinstance(events,list):
        return []
    matched={
        p["trade_id"]:p for p in positions
        if (isinstance(p,dict)
            and isinstance(p.get("trade_id"),str) and p["trade_id"]
            and p.get("epic")=="US500" and p.get("source")==SOURCE
            and p.get("side") in ("LONG","SHORT"))
    }
    records=[]
    seen=set()
    for ev in events[-MAX_EVENTS:]:
        if not isinstance(ev,dict) or ev.get("kind") not in EVENT_KINDS:
            continue
        uid=ev.get("event_id")
        if not isinstance(uid,str) or not re.fullmatch(r"[0-9a-f]{64}",uid):
            continue
        if uid in seen:
            continue
        pos=matched.get(ev.get("trade_id"))
        if not pos:
            continue
        kind=ev["kind"]
        if kind=="PAPER_OPEN":
            if pos.get("status") not in ("OPEN",*CLOSE_STATUS.values()):
                continue
            if not pos.get("opened_utc"):
                continue
        elif pos.get("status")!=CLOSE_STATUS[kind]:
            continue
        created=aware(ev.get("created_utc"))
        candle=aware(ev.get("candle_utc"))
        if created is None or candle is None:
            continue
        if kind=="PAPER_OPEN":
            description="OTWARCIE "+pos["side"]
            model=pos.get("entry_assumed_utc")
            confirmed=pos.get("opened_utc")
        else:
            description=EVENT_KINDS[kind]+" "+pos["side"]
            model=None
            confirmed=pos.get("closed_utc")
        if aware(confirmed) is None:
            continue
        attribution=method_attribution(pos)
        records.append({
            "event_id":uid,
            "trade_id":pos["trade_id"],
            "side":pos["side"],
            "kind":kind,
            "label":description,
            "method":str(attribution.get("label") or pos.get("strategy") or "BRAK"),
            "modeled_open_pl":in_poland(model) if kind=="PAPER_OPEN"
                              else "—",
            "confirmed_pl":in_poland(confirmed),
            "worker_event_pl":in_poland(created),
            "worker_event_utc":created.isoformat(),
            "event_candle_pl":in_poland(candle),
            "entry_mid":pos.get("entry_mid") if kind=="PAPER_OPEN" else None,
            "exit_mid":pos.get("exit_mid") if kind!="PAPER_OPEN" else None,
            "net_pts":pos.get("pnl_pts") if kind!="PAPER_OPEN" else None,
            "audio_delivery":"NIE POTWIERDZONO ODSŁUCHU",
        })
        seen.add(uid)
    records.sort(key=lambda r:(r["worker_event_utc"],r["event_id"]),
                 reverse=True)
    return records[:max(1,min(100,int(limit)))]


def playback_attempt_record(event,mode,*,now=None):
    """Logging an attempt is not proof of autoplay success or audibility."""
    if not isinstance(event,dict) or not isinstance(event.get("event_id"),str):
        return None
    if mode not in ("VOICE","TONE"):
        return None
    moment=now if now is not None else datetime.now(timezone.utc)
    if aware(moment) is None:
        return None
    return {
        "event_id":event["event_id"],
        "attempt_utc":moment.astimezone(timezone.utc).isoformat(),
        "attempt_pl":in_poland(moment),
        "mode":mode,
        "delivered":None,
    }


def recent_playback_attempts(prior,new,max_rows=30):
    """Stable idempotent browser session log only, no remote DB writes."""
    rows=[x for x in (prior or []) if isinstance(x,dict)
          and isinstance(x.get("event_id"),str)]
    if new and all(p["event_id"]!=new["event_id"] for p in rows):
        rows.insert(0,new)
    return rows[:max_rows]
