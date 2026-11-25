"""Owner-only browser MP3 player: guaranteed one-click manual test path.

This component uses the three existing static voice clips and optional
event-specific assets, all loaded server side. No external ElevenLabs API,
no generated broker events, no user-controlled HTML or network connections.

Audible autoplay is best effort in Chrome. A DIRECT click inside this
iframe is a browser user gesture and can unlock speech even if autoplay
was blocked. We show actual playback status, never claim that the sound
was heard just because a Python callback ran.
"""
from __future__ import annotations

import base64
from html import escape
import json
import re

from .paper_sounds import SOUND_EVENTS


def voice_player_html(data: bytes, mime: str, *, kind: str,
                      side: str | None = None, event_id: str | None = None,
                      autostart: bool = False) -> str:
    if kind not in SOUND_EVENTS:
        raise ValueError("Nieznane zdarzenie PAPER")
    if side not in (None, "LONG", "SHORT"):
        raise ValueError("Nieznany kierunek PAPER")
    if mime not in ("audio/mpeg", "audio/wav"):
        raise ValueError("Nieznany typ dźwięku")
    if not isinstance(data, bytes) or not 0 < len(data) <= 2 * 1024 * 1024:
        raise ValueError("Pusty lub zbyt duży plik audio")
    if event_id is not None and not re.fullmatch(r"[0-9a-f]{64}", event_id):
        raise ValueError("Niezaufany identyfikator zdarzenia")
    if autostart and event_id is None:
        raise ValueError("Automatycznie odtwarzamy tylko zapisane zdarzenia")

    if kind == "PAPER_OPEN":
        label = "OTWARCIE " + (side or "PAPER")
    elif kind == "PAPER_CLOSE_TP":
        label = "ZAMKNIĘCIE TAKE PROFIT"
    elif kind == "PAPER_CLOSE_SL":
        label = "ZAMKNIĘCIE STOP LOSS"
    elif kind == "PAPER_TIMEOUT":
        label = "ZAMKNIĘCIE PO CZASIE"
    elif kind == "PAPER_TRAIL_SL":
        label = "ZMIANA STOP LOSS"
    else:
        label = "ZMIANA TAKE PROFIT"

    uri = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    text = escape(label)
    src = json.dumps(uri)
    uid = json.dumps(event_id or "")
    auto = "true" if autostart else "false"
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<style>
html,body {{margin:0;background:#101c30;color:#eaf4ff;
  font-family:system-ui,-apple-system,sans-serif}}
main {{display:flex;flex-wrap:wrap;align-items:center;gap:7px;
  border:1px solid #365276;border-radius:10px;padding:9px 10px}}
button {{border:1px solid #69baff;border-radius:8px;background:#1761a2;
  color:white;font-size:13px;font-weight:650;padding:8px 12px;cursor:pointer}}
button:focus-visible {{outline:3px solid #fada5e}}
#fokus-voice-status {{font-size:12px;color:#b6cee9}}
small {{display:block;color:#9bb8dc;font-size:11px;width:100%}}
</style></head><body><main>
<button type="button" id="fokus-voice-play">▶ ODTWÓRZ GŁOS</button>
<span id="fokus-voice-status" aria-live="polite">Gotowe do odtworzenia</span>
<small>{text} · głos wyłącznie wirtualnego PAPER, bez zleceń</small>
<audio id="fokus-voice-audio" preload="auto"></audio>
</main><script>
(function(){{
  "use strict";
  const sound=document.getElementById("fokus-voice-audio");
  const info=document.getElementById("fokus-voice-status");
  const button=document.getElementById("fokus-voice-play");
  sound.src={src};
  async function play(){{
    try {{
      sound.pause();
      sound.currentTime=0;
      info.textContent="Uruchamianie nagrania...";
      await sound.play();
      info.textContent="🔊 Odtwarzanie rozpoczęte";
    }} catch (_) {{
      info.textContent="Chrome zablokował automat. Kliknij ▶, by odsłuchać.";
    }}
  }}
  button.addEventListener("click",play);
  sound.addEventListener("error",function(){{
    info.textContent="Nie udało się załadować MP3. Użyj odtwarzacza niżej.";
  }});
  const auto={auto}, eventId={uid};
  if(auto && eventId){{
    const key="fokus-audio-attempt-v2:"+eventId;
    // Never re-play old trades on each five-second Streamlit rerender.
    try {{
      if(sessionStorage.getItem(key)!=="attempted"){{
        sessionStorage.setItem(key,"attempted");
        setTimeout(function(){{
          if(document.visibilityState==="visible") play();
          else info.textContent="Karta w tle — kliknij ▶, aby odsłuchać alert.";
        }},100);
      }}
    }} catch (_) {{
      // Private mode can restrict storage, yet manual click still works.
      info.textContent="Kliknij ▶, aby odsłuchać alert.";
    }}
  }}
}})();
</script></body></html>"""


def render_voice_player(data: bytes, mime: str, *, kind: str,
                        side: str | None = None,
                        event_id: str | None = None,
                        autostart: bool = False) -> None:
    import streamlit as st
    markup = voice_player_html(
        data, mime, kind=kind, side=side,
        event_id=event_id, autostart=autostart)
    st.iframe(markup, height=102)
