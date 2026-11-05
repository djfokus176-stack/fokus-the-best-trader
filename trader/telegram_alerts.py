"""Telegram opt-in alerts for PAPER events (NOT BROKER TRADING).

At-most-one SEND ATTEMPT per event_id across restarts. The row is claimed
and committed BEFORE network send, so a crash may lose a notification.
This intentionally favors no duplicates over guaranteed delivery.
No token is ever logged, archived, or shown in error text.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import re
import sqlite3
import requests

ALLOWED_KINDS={
    "LONG_SETUP","SHORT_SETUP","PAPER_OPEN","PAPER_CLOSE_SL",
    "PAPER_CLOSE_TP","PAPER_TIMEOUT","PAPER_INVALIDATED","DATA_STALE"
}

def ensure_outbox(db):
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_attempts_v3 (
      event_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
      claim_utc TEXT NOT NULL, result TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS paper_system_events_v3 (
      event_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
      source TEXT NOT NULL, epic TEXT NOT NULL, timeframe TEXT NOT NULL,
      candle_utc TEXT NOT NULL, reason TEXT NOT NULL,created_utc TEXT NOT NULL
    )""")
    db.commit()

def record_stale_event(db,source,epic,timeframe,reason,at=None):
    """At most once per 15-minute UTC bucket, only actual DEMO stale feed."""
    if source!="Capital.com DEMO REST":
        return None
    from hashlib import sha256
    at=at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("UTC datetime required")
    bucket=int(at.timestamp())//900
    event_id=sha256(f"{source}|{epic}|{timeframe}|DATA_STALE|{bucket}".encode()).hexdigest()
    ensure_outbox(db)
    db.execute("""INSERT OR IGNORE INTO paper_system_events_v3
        (event_id,kind,source,epic,timeframe,candle_utc,reason,created_utc)
        VALUES (?,?,?,?,?,?,?,?)""",
        (event_id,"DATA_STALE",source,epic,timeframe,at.isoformat(),
        str(reason)[:250],datetime.now(timezone.utc).isoformat()))
    db.commit()
    return event_id

def _is_valid(token,chat_id):
    return (bool(re.fullmatch(r"[0-9]{6,15}:[A-Za-z0-9_-]{12,}",str(token or "")))
      and bool(re.fullmatch(r"-?[0-9]{5,20}",str(chat_id or ""))))

def _pending_events(db,now,minutes=5):
    cutoff=(now-timedelta(minutes=minutes)).isoformat()
    db.row_factory=sqlite3.Row
    return [dict(x) for x in db.execute("""
      SELECT e.event_id,e.kind,e.candle_utc,e.reason,e.created_utc,
             p.source,p.epic,p.timeframe,p.side,p.entry_mid,p.stop_mid,
             p.target_mid,p.pnl_pts,p.status,p.strategy
        FROM paper_events_v3 e
        JOIN paper_positions_v3 p ON p.trade_id=e.trade_id
       WHERE e.created_utc>=? AND e.event_id NOT IN
         (SELECT event_id FROM telegram_attempts_v3)
      UNION ALL
      SELECT e.event_id,e.kind,e.candle_utc,e.reason,e.created_utc,
             e.source,e.epic,e.timeframe,NULL,NULL,NULL,NULL,NULL,NULL,NULL
        FROM paper_system_events_v3 e
       WHERE e.created_utc>=? AND e.event_id NOT IN
         (SELECT event_id FROM telegram_attempts_v3)
      ORDER BY created_utc ASC LIMIT 10""",(cutoff,cutoff))]

def _render(row):
    status=str(row.get("kind") or "").upper()
    if status not in ALLOWED_KINDS:
        return ""
    lines=["🧪 FOKU$ THE BEST TRADER — PAPER",
           f"Zdarzenie: {status}",
           f"Instrument: {row.get('epic')} | TF: {row.get('timeframe')}",
           f"Źródło: {row.get('source')}",
           f"Świeca UTC: {row.get('candle_utc')}",
           f"Przyczyna: {str(row.get('reason',''))[:200]}"]
    if row.get("side"):
        lines.append(f"Kierunek: {row['side']} | Strategia: {row.get('strategy')}")
    if status=="PAPER_OPEN" and row.get("entry_mid") is not None:
        lines.append(f"Entry MID: {row['entry_mid']} | SL: {row['stop_mid']} | TP: {row['target_mid']}")
    if status in ("PAPER_CLOSE_SL","PAPER_CLOSE_TP","PAPER_TIMEOUT") and row.get("pnl_pts") is not None:
        lines.append(f"Netto PAPER: {row['pnl_pts']:+.2f} pkt")
    lines.append("Wyłącznie symulacja PAPER, nie zlecenie ani rekomendacja.")
    return "\n".join(lines)

def dispatch_alerts(db,token,chat_id,enabled=False,post=None,now=None, max_events=10):
    """Exactly one attempted delivery per event_id, no background promises."""
    if not enabled:
        return {"status":"DISABLED","attempted":0,"sent":0,"failed":0}
    if not _is_valid(token,chat_id):
        return {"status":"NOT_CONFIGURED","attempted":0,"sent":0,"failed":0}
    ensure_outbox(db)
    now=now or datetime.now(timezone.utc)
    post=post or requests.post
    attempted=sent=failed=0
    for row in _pending_events(db,now)[:max_events]:
        body=_render(row)
        if not body:
            continue
        # Atomic claim BEFORE sending; repeated scans/process restarts do
        # not send twice. Delivery can be LOST after claim on crash.
        db.execute("BEGIN IMMEDIATE")
        try:
            cursor=db.execute("""INSERT OR IGNORE INTO telegram_attempts_v3
             (event_id,kind,claim_utc,result) VALUES (?,?,?,?)""",
             (row["event_id"],row["kind"],datetime.now(timezone.utc).isoformat(),"CLAIMED"))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        if cursor.rowcount!=1:
            continue
        attempted+=1
        try:
            response=post("https://api.telegram.org/bot"+token+"/sendMessage",
                data={"chat_id":chat_id,"text":body,
                      "disable_web_page_preview":"true"},timeout=10)
            good=(response.status_code==200 and bool(response.json().get("ok")))
        except (requests.RequestException,ValueError,TypeError,AttributeError):
            good=False
        state="SENT" if good else "FAILED_NO_RETRY"
        db.execute("UPDATE telegram_attempts_v3 SET result=? WHERE event_id=?",
                   (state,row["event_id"]))
        db.commit()
        sent+=int(good)
        failed+=int(not good)
    return {"status":"OK","attempted":attempted,"sent":sent,"failed":failed}
