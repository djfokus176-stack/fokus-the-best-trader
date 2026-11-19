"""Read-only, simple journal of the bot's automatic simulated trades.

Read exclusively from the verified, existing durable v3 positions. No new
entries, fills, broker orders, financial amounts, or reconstructed trades.
PENDING is not OPEN; INVALIDATED has no made-up P&L. Only positions whose
original setup_reason proves AUTO origin appear in this owner's main view.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from .paper_method_labels import method_attribution

SOURCE = "Capital.com DEMO REST"
WARSAW = ZoneInfo("Europe/Warsaw")
CLOSED = {"CLOSED_TP": "TP", "CLOSED_SL": "SL",
          "CLOSED_TIMEOUT": "CZAS"}
STATES = {"PENDING": "OCZEKUJE", "OPEN": "OTWARTA",
          "INVALIDATED": "UNIEWAŻNIONA", **{
              key: "ZAMKNIĘTA • " + reason for key,reason in CLOSED.items()}}


def _utc(value):
    if not isinstance(value,str) or not value.strip():
        return None
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,OverflowError):
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None


def _local(value):
    t=_utc(value)
    return t.astimezone(WARSAW).strftime("%d.%m.%Y %H:%M") if t else "—"


def _price(value):
    if isinstance(value,bool):
        return None
    try:
        number=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return round(number,2) if isfinite(number) else None


def auto_sim_journal(payload, *, limit=20):
    """Summarize AUTO-only confirmed states from one saved checkpoint."""
    blank={"known":False,"opened":0,"closed":0,"active":None,"pending":None,
           "invalidated":0,"incomplete":0,"latest_closed":None,
           "net_pts":0.0,"rows":[]}
    if not isinstance(payload,dict) or not isinstance(payload.get("tables"),dict):
        return blank
    meta=payload.get("meta")
    if not isinstance(meta,dict) or meta.get("source")!=SOURCE or meta.get("epic")!="US500":
        return blank
    raw=payload["tables"].get("paper_positions_v3")
    if not isinstance(raw,list):
        return blank
    result={**blank,"known":True}
    seen=set()
    completed=[]
    active=[]
    pending=[]
    for p in raw:
        if (not isinstance(p,dict) or p.get("source")!=SOURCE
                or p.get("epic")!="US500" or p.get("side") not in ("LONG","SHORT")
                or p.get("status") not in STATES):
            result["incomplete"]+=1
            continue
        trade_id=p.get("trade_id")
        if not isinstance(trade_id,str) or not trade_id or trade_id in seen:
            result["incomplete"]+=1
            continue
        seen.add(trade_id)
        attr=method_attribution(p)
        if not attr["label"].startswith("AUTO → "):
            # Preserve other experiments in their own existing archives;
            # do not label them as automatically chosen by the six-strategy bot.
            continue
        status=p["status"]
        item={
            "ID":trade_id[:12],
            "Kierunek":p["side"],
            "Strategia":attr["method"],
            "Status":STATES[status],
            "Otwarcie (Polska)":_local(p.get("opened_utc")),
            "Zamknięcie (Polska)":_local(p.get("closed_utc")),
            "Wejście (pkt)":_price(p.get("entry_mid")),
            "Wyjście (pkt)":_price(p.get("exit_mid")),
            "SL (pkt)":_price(p.get("stop_mid")),
            "TP (pkt)":_price(p.get("target_mid")),
            "Wynik (pkt)":None,
        }
        if status=="PENDING":
            item["Status"]="OCZEKUJE NA POTWIERDZENIE"
            if _utc(p.get("setup_utc")) is None:
                result["incomplete"]+=1
                continue
            pending.append((_utc(p["setup_utc"]),item))
            continue
        if status=="INVALIDATED":
            result["invalidated"]+=1
            continue
        opened=_utc(p.get("opened_utc"))
        if opened is None or item["Wejście (pkt)"] is None:
            result["incomplete"]+=1
            continue
        if status=="OPEN":
            active.append((opened,item))
            continue
        closed=_utc(p.get("closed_utc"))
        pnl=_price(p.get("pnl_pts"))
        if (closed is None or closed<opened or
                item["Wyjście (pkt)"] is None or pnl is None):
            result["incomplete"]+=1
            continue
        item["Wynik (pkt)"]=pnl
        completed.append((closed,item))
        result["net_pts"]+=pnl
    active.sort(key=lambda t:t[0],reverse=True)
    pending.sort(key=lambda t:t[0],reverse=True)
    completed.sort(key=lambda t:t[0],reverse=True)
    result["active"]=active[0][1] if active else None
    result["pending"]=pending[0][1] if pending else None
    result["closed"]=len(completed)
    result["opened"]=len(active)+len(completed)
    result["latest_closed"]=completed[0][1] if completed else None
    result["net_pts"]=round(result["net_pts"],2)
    result["rows"]=[x[1] for x in completed[:max(1,min(100,int(limit)))]]
    return result
