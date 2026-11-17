"""CLOUD voice regressions: real PAPER only, baseline, uniqueness, safety."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path

from trader.cloud_paper_audio import (
    cloud_paper_audio_events, advance_cloud_audio
)
from trader.paper_sounds import alert_audio, voice_filename

NOW="2026-11-17T15:00:00+00:00"


def make_event(kind, trade_id, created, idx):
    return {
        "event_id": sha256(f"{trade_id}:{kind}:{idx}".encode()).hexdigest(),
        "trade_id": trade_id,
        "kind": kind, "created_utc": created,
        "candle_utc": created,
        "reason": "test",
    }


def fixture(*, status="OPEN", side="LONG", events=None):
    return {
        "schema": 1,
        "meta": {"source": "Capital.com DEMO REST", "epic": "US500"},
        "tables": {
            "paper_positions_v3": [
                {"trade_id": "p1", "source": "Capital.com DEMO REST",
                 "epic": "US500", "side": side, "status": status}
            ],
            "paper_events_v3": list(events or []),
        },
    }


def test_no_marker_voice_without_an_actual_paper_event():
    payload=fixture()
    payload["last_vote_audit"]={"watch":{"side":"LONG","score":6},
                                "rows":[{"raw":"SHORT","after_mtf":"WAIT"}]}
    assert cloud_paper_audio_events(payload,now=NOW)==[]


def test_confirmed_open_long_can_play_once_after_arm():
    e=make_event("PAPER_OPEN","p1",NOW,1)
    prior=cloud_paper_audio_events(fixture(),now=NOW)
    cursor,pending,play=advance_cloud_audio(prior,None,[],enabled=True)
    assert cursor=="__EMPTY__" and play is None
    rows=cloud_paper_audio_events(fixture(events=[e]),now=NOW)
    cursor,pending,play=advance_cloud_audio(rows,cursor,pending,enabled=True)
    assert play["side"]=="LONG" and play["kind"]=="PAPER_OPEN"
    cursor,pending,play=advance_cloud_audio(rows,cursor,pending,enabled=True)
    assert play is None and not pending


def test_close_sound_has_correct_side_and_real_matching_status():
    e=make_event("PAPER_CLOSE_TP","p1",NOW,1)
    row=cloud_paper_audio_events(
        fixture(status="CLOSED_TP",side="SHORT",events=[e]),now=NOW)
    assert len(row)==1 and row[0]["side"]=="SHORT"
    assert cloud_paper_audio_events(
        fixture(status="OPEN",events=[e]),now=NOW)==[]
    assert cloud_paper_audio_events(
        fixture(status="CLOSED_SL",events=[e]),now=NOW)==[]


def test_open_and_close_in_same_snapshot_are_queued_oldest_first():
    t0="2026-11-17T14:59:55+00:00"
    e1=make_event("PAPER_OPEN","p1",t0,1)
    e2=make_event("PAPER_CLOSE_SL","p1",NOW,2)
    rows=cloud_paper_audio_events(
        fixture(status="CLOSED_SL",events=[e2,e1]),now=NOW)
    assert [x["kind"] for x in rows]==["PAPER_CLOSE_SL","PAPER_OPEN"]
    cursor,waiting,play=advance_cloud_audio(rows,"__EMPTY__",[],enabled=True)
    assert play["kind"]=="PAPER_OPEN"
    cursor,waiting,play=advance_cloud_audio(rows,cursor,waiting,enabled=True)
    assert play["kind"]=="PAPER_CLOSE_SL"
    cursor,waiting,play=advance_cloud_audio(rows,cursor,waiting,enabled=True)
    assert play is None


def test_old_events_wrong_market_and_unknown_ids_are_not_replayed():
    older=make_event("PAPER_OPEN","p1","2026-11-17T14:30:00+00:00",1)
    bad=make_event("PAPER_OPEN","p1",NOW,2)
    bad["event_id"]="not-a-verified-event"
    assert cloud_paper_audio_events(fixture(events=[older,bad]),now=NOW)==[]
    e=make_event("PAPER_OPEN","p1",NOW,3)
    p=fixture(events=[e])
    p["meta"]["epic"]="GER40"
    assert cloud_paper_audio_events(p,now=NOW)==[]
    p=fixture(events=[e])
    p["tables"]["paper_positions_v3"][0]["source"]="LIVE"
    assert cloud_paper_audio_events(p,now=NOW)==[]


def test_disabled_audio_discards_queue_and_enabling_resets_baseline():
    one=make_event("PAPER_OPEN","p1",NOW,1)
    rows=cloud_paper_audio_events(fixture(events=[one]),now=NOW)
    cursor,waiting,play=advance_cloud_audio(rows,None,[],enabled=True)
    assert play is None and not waiting and cursor==one["event_id"]
    cursor,waiting,play=advance_cloud_audio(rows,cursor,[one],enabled=False)
    assert play is None and waiting==[]
    assert cursor==one["event_id"]


def test_expired_cursor_resyncs_without_old_alert_replay():
    row=cloud_paper_audio_events(
        fixture(events=[make_event("PAPER_OPEN","p1",NOW,1)]),now=NOW)
    cursor,pending,play=advance_cloud_audio(
        row,"missing-from-window",[],enabled=True)
    assert cursor==row[0]["event_id"]
    assert pending==[] and play is None


def test_mp3_voice_mapping_is_explicit_and_tone_fallback_is_functional(tmp_path):
    assert voice_filename("PAPER_OPEN","LONG")=="open_long.mp3"
    assert voice_filename("PAPER_OPEN","SHORT")=="open_short.mp3"
    assert voice_filename("PAPER_CLOSE_SL","SHORT")=="close_stop.mp3"
    audio,mime,used=alert_audio(
        "PAPER_OPEN","LONG",voice_enabled=True,directory=tmp_path)
    assert mime=="audio/wav" and used=="TONE" and audio[:4]==b"RIFF"


def test_cloud_view_has_voice_without_modifying_worker_or_chart_data():
    text=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf8")
    assert "render_cloud_paper_voice(remote,url=url)" in text
    assert "advance_cloud_audio(" in text
    assert "st.audio(content,format=mime,autoplay=audio_event is not None)" in text
    assert "queue_paper(" not in text
    assert "CapitalReadOnly(" not in text
