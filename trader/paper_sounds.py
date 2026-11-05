"""Deterministic browser-side PAPER notification sounds; no secret and no orders.

Only new archived events after the listener is armed can trigger a sound.
Playback may be blocked by browser autoplay policy; manual interaction needed.
"""
from __future__ import annotations
import io
import math
import struct
import wave


SOUND_EVENTS={
    "PAPER_OPEN": "Odtworzone otwarcie PAPER",
    "PAPER_CLOSE_TP": "PAPER: zamknięcie TP",
    "PAPER_CLOSE_SL": "PAPER: zamknięcie SL",
    "PAPER_TIMEOUT": "PAPER: zamknięcie po czasie",
    "PAPER_TRAIL_SL": "PAPER: podciągnięto stop loss",
    "PAPER_EXTEND_TP": "PAPER: wydłużono cel zysku",
}
PRIORITY=("PAPER_CLOSE_SL","PAPER_CLOSE_TP","PAPER_TIMEOUT","PAPER_OPEN",
          "PAPER_EXTEND_TP","PAPER_TRAIL_SL")


def unseen_paper_event(events, last_seen):
    """Returns (newest event id, event to play or None). Ordered newest-first."""
    rows=list(events or [])
    newest=rows[0].get("event_id") if rows else last_seen
    if last_seen is None:
        return newest,None  # First render is BASELINE, not a replay alarm.
    relevant=[]
    for event in rows:
        if event.get("event_id")==last_seen:
            break
        if event.get("kind") in SOUND_EVENTS:
            relevant.append(event)
    if not relevant:
        return newest,None
    rank={kind:i for i,kind in enumerate(PRIORITY)}
    chosen=min(relevant,key=lambda e:rank.get(e.get("kind"),100))
    return newest,chosen


def wav_notice(kind,rate=12000):
    """Short generated beep; no external media, no network; deterministic WAV."""
    if kind not in SOUND_EVENTS:
        raise ValueError("Nieznany sygnał PAPER")
    if kind=="PAPER_CLOSE_SL":
        notes=(440,330,220)
    elif kind=="PAPER_CLOSE_TP":
        notes=(550,720,880)
    elif kind=="PAPER_OPEN":
        notes=(550,690)
    elif kind=="PAPER_TIMEOUT":
        notes=(420,390)
    else:
        notes=(650,740)
    width=rate//7
    frames=bytearray()
    for freq in notes:
        for i in range(width):
            envelope=min(1.0,i/200)*min(1.0,(width-i)/200)
            value=int(9800*envelope*math.sin(2*math.pi*freq*i/rate))
            frames.extend(struct.pack("<h",value))
        frames.extend(b"\x00\x00"*(rate//35))
    stream=io.BytesIO()
    with wave.open(stream,"wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return stream.getvalue()
