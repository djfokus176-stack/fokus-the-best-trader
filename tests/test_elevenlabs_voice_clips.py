"""ElevenLabs static-clip integration must be safe, optional and per-event."""
from pathlib import Path
import pytest
from trader.paper_sounds import (
    voice_clip, voice_filename, alert_audio, wav_notice, VOICE_FILES,
)


@pytest.mark.parametrize("kind,side,filename",[
    ("PAPER_OPEN","LONG","open_long.mp3"),
    ("PAPER_OPEN","SHORT","open_short.mp3"),
    ("PAPER_CLOSE_TP",None,"close_profit.mp3"),
    ("PAPER_CLOSE_SL",None,"close_stop.mp3"),
    ("PAPER_TIMEOUT",None,"close_timeout.mp3"),
    ("PAPER_TRAIL_SL",None,"move_stop.mp3"),
    ("PAPER_EXTEND_TP",None,"extend_target.mp3"),
])
def test_voice_filename_is_whitelisted_by_event_and_side(kind,side,filename):
    assert voice_filename(kind,side)==filename


def test_invalid_event_or_missing_side_does_not_read_arbitrary_file(tmp_path):
    (tmp_path/"secret.mp3").write_bytes(b"ID3"+"x".encode()*200)
    assert voice_filename("../../../secret.mp3") is None
    assert voice_filename("PAPER_OPEN","WAIT") is None
    assert voice_clip("PAPER_OPEN","WAIT",directory=tmp_path) is None


def test_mp3_plays_for_matching_event_and_uses_correct_mime(tmp_path):
    binary=b"ID3"+b"x"*200
    (tmp_path/"open_long.mp3").write_bytes(binary)
    data,mime,mode=alert_audio("PAPER_OPEN","LONG",voice_enabled=True,directory=tmp_path)
    assert data==binary and mime=="audio/mpeg" and mode=="VOICE"
    # SHORT must NOT play LONG by mistake.
    data,mime,mode=alert_audio("PAPER_OPEN","SHORT",voice_enabled=True,directory=tmp_path)
    assert mode=="TONE" and mime=="audio/wav" and data.startswith(b"RIFF")


def test_voice_disabled_always_uses_original_tone(tmp_path):
    (tmp_path/"close_stop.mp3").write_bytes(b"ID3"+b"x"*200)
    audio,mime,used=alert_audio("PAPER_CLOSE_SL",voice_enabled=False,directory=tmp_path)
    assert audio==wav_notice("PAPER_CLOSE_SL")
    assert mime=="audio/wav" and used=="TONE"


def test_invalid_or_too_large_mp3_falls_back_without_crash(tmp_path):
    p=tmp_path/"close_profit.mp3"
    p.write_bytes(b"not audio")
    assert alert_audio("PAPER_CLOSE_TP",voice_enabled=True,directory=tmp_path)[2]=="TONE"
    p.write_bytes(b"ID3"+b"x"*(2*1024*1024))
    assert voice_clip("PAPER_CLOSE_TP",directory=tmp_path) is None


def test_unsupported_kind_returns_no_voice():
    assert voice_filename("PAPER_OPEN","RANDOM") is None
    assert voice_filename("PAPER_INVALIDATED") is None
    assert sorted(VOICE_FILES)==sorted([
        "PAPER_CLOSE_TP","PAPER_CLOSE_SL","PAPER_TIMEOUT",
        "PAPER_TRAIL_SL","PAPER_EXTEND_TP"])


def test_shared_close_mp3_covers_take_profit_stop_loss_and_timeout(tmp_path):
    from trader.paper_sounds import new_paper_events
    recording=b"ID3"+b"three voice file"*10
    (tmp_path/"close.mp3").write_bytes(recording)
    for event in ("PAPER_CLOSE_TP","PAPER_CLOSE_SL","PAPER_TIMEOUT"):
        data,mime,mode=alert_audio(event,voice_enabled=True,directory=tmp_path)
        assert (data,mime,mode)==(recording,"audio/mpeg","VOICE")
    # Event-specific clip can still override shared 'Zamknij'.
    special=b"ID3"+b"take profit"*12
    (tmp_path/"close_profit.mp3").write_bytes(special)
    assert alert_audio("PAPER_CLOSE_TP",voice_enabled=True,directory=tmp_path)[0]==special
    assert alert_audio("PAPER_CLOSE_SL",voice_enabled=True,directory=tmp_path)[0]==recording


def test_open_and_close_same_scan_play_separately_in_chronological_queue():
    from trader.paper_sounds import new_paper_events
    opened={"event_id":"opened","kind":"PAPER_OPEN","trade_id":"one"}
    closed={"event_id":"closed","kind":"PAPER_CLOSE_TP","trade_id":"one"}
    # The database returns newest-first and the listener was already armed
    last,new=new_paper_events([closed,opened],"__EMPTY__")
    assert last=="closed"
    assert [e["kind"] for e in new]==["PAPER_OPEN","PAPER_CLOSE_TP"]
    last,new=new_paper_events([closed,opened],last)
    assert not new
    # Existing prior events are not replayed on initial page load.
    assert new_paper_events([closed,opened],None)==("closed",[])
    assert new_paper_events([],"__EMPTY__")==("__EMPTY__",[])
