"""PAPER AI chat transcript helpers (per browser session).

Auto-reruns must never erase answers. Do not persist raw prompts or API
keys on a public filesystem. Messages are shown even if market data expires.
"""
from __future__ import annotations
from datetime import datetime, timezone

def append_message(history, role: str, content: str, context_utc=None, max_messages=36):
    if role not in ("user","assistant"):
        raise ValueError("Invalid role")
    text=str(content or "").strip()
    if not text:
        raise ValueError("Cannot store an empty AI message")
    msg={"role":role,"content":text[:16000],
         "time_utc":datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
         "market_candle_utc":str(context_utc or "BRAK")}
    return (list(history or []) + [msg])[-max(2,int(max_messages)):]

def renderable_history(history):
    """Read-only normalized transcript (no empty assistant messages)."""
    return [m for m in list(history or []) if isinstance(m,dict)
            and m.get("role") in ("user","assistant") and str(m.get("content","")).strip()]

def preview_context(payload):
    """Expose exactly what will be sent to AI, without client-side secrets."""
    if not isinstance(payload,dict):
        return {"instrument":"BRAK","candle":"BRAK","decision":"BRAK","n_candles":0}
    return {"instrument":payload.get("instrument","BRAK"),
            "candle":payload.get("last_closed_utc","BRAK"),
            "decision":payload.get("decision","BRAK"),
            "n_candles":len(payload.get("last_12_closed_candles") or [])}
