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


# Prerecorded ElevenLabs clips are optional static MP3 assets:
# NO ElevenLabs API key, no extra generation costs at alert time.
# Asset filenames are a fixed allowlist; trade metadata never becomes a path.
from pathlib import Path

VOICE_DIR=Path(__file__).resolve().parents[1]/"assets"/"voices"
VOICE_FILES={
    "PAPER_CLOSE_TP":"close_profit.mp3",
    "PAPER_CLOSE_SL":"close_stop.mp3",
    "PAPER_TIMEOUT":"close_timeout.mp3",
    "PAPER_TRAIL_SL":"move_stop.mp3",
    "PAPER_EXTEND_TP":"extend_target.mp3",
}


def voice_filename(kind, side=None):
    """Return the fixed voice clip for an actual archived PAPER event."""
    if kind=="PAPER_OPEN":
        return {"LONG":"open_long.mp3","SHORT":"open_short.mp3"}.get(side)
    return VOICE_FILES.get(kind)


def voice_clip(kind, side=None, *, directory=None):
    """Load an optional local MP3; no network or arbitrary path access.

    Missing/invalid files fall back to the existing event-specific WAV tone.
    Each clip is limited to 2 MiB to avoid memory spikes on Streamlit Cloud.
    """
    filename=voice_filename(kind,side)
    if not filename:
        return None
    directory=VOICE_DIR if directory is None else Path(directory)
    # Uploaded single 'zamknij' clip can cover TP, SL and TIMEOUT,
    # while optional event-specific clips have priority when present.
    choices=[filename]
    if kind in ("PAPER_CLOSE_TP","PAPER_CLOSE_SL","PAPER_TIMEOUT"):
        choices.append("close.mp3")
    for choice in choices:
        path=directory/choice
        try:
            if not path.is_file() or not (0<path.stat().st_size<=2*1024*1024):
                continue
            data=path.read_bytes()
            if data[:3]==b"ID3" or (
                len(data)>2 and data[0]==255 and data[1]&224==224):
                return data
        except OSError:
            continue
    return None


def alert_audio(kind, side=None, *, voice_enabled=False, directory=None):
    """Return audio bytes, MIME type and actual mode used (VOICE or TONE)."""
    if voice_enabled:
        mp3=voice_clip(kind,side,directory=directory)
        if mp3 is not None:
            return mp3,"audio/mpeg","VOICE"
    return wav_notice(kind),"audio/wav","TONE"



def new_paper_events(events,last_seen):
    """Collect all newly archived alerts in true chronological order.

    This avoids losing OPEN when it and CLOSE are recorded by one scan.
    First open of the page establishes baseline without replaying history.
    """
    rows=list(events or [])
    newest=rows[0].get("event_id") if rows else last_seen
    if last_seen is None:
        return newest,[]
    unseen=[]
    for event in rows:
        if event.get("event_id")==last_seen:
            break
        if event.get("kind") in SOUND_EVENTS:
            unseen.append(event)
    return newest,list(reversed(unseen))
