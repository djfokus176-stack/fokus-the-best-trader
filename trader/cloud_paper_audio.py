"""Verified CLOUD PAPER event sound feed (read-only, no orders/network).

All audio comes from persisted PAPER v3 event IDs, never from watch/strategy
markers or price movements. First use establishes a baseline without replay.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .paper_sounds import SOUND_EVENTS, new_paper_events

SOURCE = "Capital.com DEMO REST"
CLOSE_STATUSES = {
    "PAPER_CLOSE_TP": "CLOSED_TP",
    "PAPER_CLOSE_SL": "CLOSED_SL",
    "PAPER_TIMEOUT": "CLOSED_TIMEOUT",
}
OPEN_STATUSES = {"OPEN", "CLOSED_TP", "CLOSED_SL", "CLOSED_TIMEOUT"}
MAX_AGE_SECONDS = 900


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def cloud_paper_audio_events(payload, *, now=None):
    """Newest-first verified PAPER event records with side for voice.

    A marker on a chart, early-watch hint or candidate LONG/SHORT NEVER
    creates an audio event. At most 150 recent event records are inspected.
    """
    if not isinstance(payload, dict):
        return []
    meta = payload.get("meta")
    tables = payload.get("tables")
    if (not isinstance(meta, dict) or not isinstance(tables, dict)
            or meta.get("epic") != "US500" or meta.get("source") != SOURCE):
        return []
    positions = tables.get("paper_positions_v3")
    events = tables.get("paper_events_v3")
    if not isinstance(positions, list) or not isinstance(events, list):
        return []
    current = _utc(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        return []
    matched = {}
    for pos in positions:
        if (not isinstance(pos, dict) or pos.get("epic") != "US500"
                or pos.get("source") != SOURCE
                or pos.get("side") not in ("LONG", "SHORT")
                or not isinstance(pos.get("trade_id"), str)):
            continue
        matched[pos["trade_id"]] = pos
    result = []
    for ev in events[-150:]:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        uid = ev.get("event_id")
        trade_id = ev.get("trade_id")
        if kind not in SOUND_EVENTS or not isinstance(uid, str):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", uid):
            continue
        position = matched.get(trade_id)
        if not position:
            continue
        status = position.get("status")
        if kind == "PAPER_OPEN" and status not in OPEN_STATUSES:
            continue
        if kind in CLOSE_STATUSES and status != CLOSE_STATUSES[kind]:
            continue
        if kind in ("PAPER_TRAIL_SL", "PAPER_EXTEND_TP") and status not in OPEN_STATUSES:
            continue
        created = _utc(ev.get("created_utc"))
        if created is None:
            continue
        age = (current - created).total_seconds()
        if not (0 <= age <= MAX_AGE_SECONDS):
            continue
        result.append({
            "event_id": uid,
            "trade_id": trade_id,
            "kind": kind,
            "side": position["side"],
            "created_utc": created.isoformat(),
        })
    # Checkpoint rows are normally not guaranteed ordered. Persisted created
    # timestamps and deterministic IDs are the sole order (no invented time).
    result.sort(key=lambda r: (r["created_utc"], r["event_id"]),
                reverse=True)
    return result


def advance_cloud_audio(events, cursor, queued, *, enabled):
    """Advance session cursor and return one event to play (oldest first).

    No old alert on first visit or after switching audio on. Drop the queue
    when disabled. If the saved cursor vanished from bounded history, resync
    instead of replaying unknown past events.
    """
    rows = list(events or [])
    head = rows[0]["event_id"] if rows else "__EMPTY__"
    if not enabled:
        return head, [], None
    if cursor is None:
        return head, [], None
    if cursor not in (head, "__EMPTY__") and all(
            ev["event_id"] != cursor for ev in rows):
        return head, [], None
    # new_paper_events only recognizes SOUND_EVENTS from real v3 records.
    newer, discovered = new_paper_events(rows, cursor)
    waiting = list(queued or []) + discovered
    waiting = waiting[-16:]
    return (newer or head), waiting[1:], (waiting[0] if waiting else None)
