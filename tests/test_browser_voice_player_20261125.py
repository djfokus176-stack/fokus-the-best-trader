"""Browser voice safety tests; synthetic audio bytes, no external API."""
import hashlib
from pathlib import Path
import pytest

from trader.browser_voice_player import voice_player_html
from trader.paper_sounds import alert_audio


def test_one_click_manual_mp3_player_has_real_voice_and_no_network():
    audio,mime,used=alert_audio("PAPER_OPEN","LONG",voice_enabled=True)
    assert used=="VOICE" and mime=="audio/mpeg"
    assert audio[:3]==b"ID3" or (audio[0]==255 and audio[1]&224==224)
    html=voice_player_html(audio,mime,kind="PAPER_OPEN",side="LONG")
    assert 'id="fokus-voice-play"' in html
    assert 'id="fokus-voice-status"' in html
    assert "button.addEventListener(\"click\",play)" in html
    assert "await sound.play()" in html
    assert "Chrome zablokował" in html
    assert "OTWARCIE LONG" in html
    assert "data:audio/mpeg;base64," in html
    assert not any(url in html for url in (
        "https://api.elevenlabs", "https://api.capital", "http://"))


def test_autoplay_requires_verified_event_id_and_is_deduplicated():
    fake=hashlib.sha256(b"paper-trade-test").hexdigest()
    html=voice_player_html(b"RIFFtestWAVE", "audio/wav",
                           kind="PAPER_CLOSE_SL",side="SHORT",
                           event_id=fake,autostart=True)
    assert f'"{fake}"' in html
    assert "const auto=true" in html
    assert "sessionStorage.getItem(key)" in html
    assert "sound.currentTime=0" in html
    assert "ZAMKNIĘCIE STOP LOSS" in html
    assert "Karta w tle" in html
    with pytest.raises(ValueError,match="zapisane"):
        voice_player_html(b"x","audio/wav",kind="PAPER_OPEN",
                          side="LONG",autostart=True)


@pytest.mark.parametrize("args",[
    {"kind":"DROP TABLE"},
    {"kind":"PAPER_OPEN","side":"<script>alert(1)</script>"},
    {"kind":"PAPER_OPEN","event_id":"invalid"},
    {"kind":"PAPER_OPEN","mime":"text/html"},
])
def test_untrusted_event_cannot_inject_browser_markup(args):
    info={"kind":"PAPER_OPEN","side":"LONG","mime":"audio/wav"}
    info.update(args)
    with pytest.raises(ValueError):
        voice_player_html(b"not-a-real-audio-file",info.pop("mime"),**info)


def test_voice_ui_is_never_bound_to_raw_chart_signals():
    app=Path("app.py").read_text(encoding="utf8")
    cloud=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    assert "render_voice_player(audio,mime,kind=sound_kind,side=sound_side)" in app
    assert "advance_cloud_audio(" in cloud
    assert "render_voice_player(" in cloud
    assert "st.audio(content,format=mime,autoplay=False)" in cloud
    assert "queue_paper(" not in cloud
    assert "CapitalReadOnly(" not in cloud
