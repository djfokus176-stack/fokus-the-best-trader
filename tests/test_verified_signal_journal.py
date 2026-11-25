"""Persisted worker signal time != chart model entry != audible notification."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path

from trader.verified_signal_journal import (
    verified_signal_rows,playback_attempt_record,recent_playback_attempts,
)

SOURCE="Capital.com DEMO REST"


def positions(status="CLOSED_TP",side="LONG"):
    return [{
        "trade_id":"proof-1","source":SOURCE,"epic":"US500",
        "side":side,"status":status,"strategy":"EMA PULLBACK",
        "setup_reason":"AUTO PAPER (eksperyment 1 sygnału) | zdarzenie",
        "entry_assumed_utc":"2026-11-19T11:47:00+00:00",
        "opened_utc":"2026-11-19T11:48:00+00:00",
        "entry_detected_utc":"2026-11-19T11:49:00+00:00",
        "entry_mid":7416.6,"closed_utc":"2026-11-19T12:08:00+00:00",
        "exit_mid":7412.4,"pnl_pts":-4.2,
    }]


def event(kind="PAPER_OPEN", created="2026-11-19T11:49:01+00:00",
          candle="2026-11-19T11:48:00+00:00",unique="first"):
    return {
        "event_id":sha256(unique.encode()).hexdigest(),
        "trade_id":"proof-1",
        "kind":kind,
        "created_utc":created,
        "candle_utc":candle,
        "reason":"Test modelowy",
    }


def payload(status="CLOSED_TP",side="LONG",events=None):
    return {
        "meta":{"source":SOURCE,"epic":"US500"},
        "tables":{
            "paper_positions_v3":positions(status,side),
            "paper_events_v3":[dict(e) for e in (events or [])],
        },
    }


def test_exact_pl_model_confirmation_and_actual_persisted_worker_event():
    e=event()
    v=verified_signal_rows(payload(events=[e]))
    assert len(v)==1
    assert v[0]["label"]=="OTWARCIE LONG"
    assert v[0]["modeled_open_pl"]=="19.11.2026 12:47"
    assert v[0]["confirmed_pl"]=="19.11.2026 12:48"
    assert v[0]["worker_event_pl"]=="19.11.2026 12:49"
    assert v[0]["event_candle_pl"]=="19.11.2026 12:48"
    assert v[0]["audio_delivery"]=="NIE POTWIERDZONO ODSŁUCHU"
    assert v[0]["method"].startswith("AUTO")


def test_persistent_journal_still_shows_older_events_but_never_replays_voice():
    e=event()
    # Server events do not expire from this display just because they are
    # older than live audio 15 minute notification window.
    v=verified_signal_rows(payload(events=[e]))
    assert len(v)==1
    t=datetime(2026,11,19,16,10,tzinfo=timezone.utc)
    p=playback_attempt_record(
        {"event_id":e["event_id"]},"VOICE",now=t)
    assert p["attempt_pl"]=="19.11.2026 17:10"
    assert p["delivered"] is None  # no fake acknowledgement of sound
    assert len(recent_playback_attempts([p],p))==1
    assert recent_playback_attempts([],None)==[]


def test_no_queued_watch_pending_raw_or_unmatched_broker_events():
    e=event()
    assert verified_signal_rows(payload(status="PENDING",events=[e]))==[]
    assert verified_signal_rows(payload(events=[]))==[]
    q=payload(events=[e])
    q["meta"]["source"]="Capital.com LIVE REST"
    assert verified_signal_rows(q)==[]
    q=payload(events=[e])
    q["tables"]["paper_positions_v3"][0]["epic"]="GER40"
    assert verified_signal_rows(q)==[]
    q=payload(events=[e])
    q["tables"]["paper_events_v3"][0]["event_id"]="not-verified"
    assert verified_signal_rows(q)==[]
    q=payload(events=[e])
    q["tables"]["paper_events_v3"][0]["trade_id"]="wrong-trade"
    assert verified_signal_rows(q)==[]
    q=payload(events=[e])
    q["last_vote_audit"]={"watch":{"side":"LONG","score":6}}
    assert len(verified_signal_rows(q))==1


def test_close_rows_require_exact_stored_close_and_include_net_pts():
    e1=event()
    e2=event(kind="PAPER_CLOSE_TP",
             created="2026-11-19T12:08:04+00:00",
             candle="2026-11-19T12:08:00+00:00",unique="second")
    v=verified_signal_rows(payload(status="CLOSED_TP",events=[e1,e2]))
    assert [x["kind"] for x in v]==["PAPER_CLOSE_TP","PAPER_OPEN"]
    assert v[0]["label"]=="ZAMKNIĘCIE TP LONG"
    assert v[0]["net_pts"]==-4.2
    assert v[0]["modeled_open_pl"]=="—"
    assert v[0]["worker_event_pl"]=="19.11.2026 13:08"
    assert verified_signal_rows(payload(status="OPEN",events=[e2]))==[]
    assert verified_signal_rows(payload(status="CLOSED_SL",events=[e2]))==[]


def test_dedup_multiple_copies_of_same_event_by_exact_id():
    e=event()
    rows=verified_signal_rows(payload(events=[e,e,e]))
    assert len(rows)==1


def test_browser_audio_attempt_not_confused_with_heard_confirmed_voice():
    e=event()
    attempted=playback_attempt_record(
        {"event_id":e["event_id"]},"TONE",
        now=datetime(2026,11,19,12,0,tzinfo=timezone.utc))
    assert attempted["mode"]=="TONE"
    assert attempted["delivered"] is None
    assert playback_attempt_record(
        {"event_id":e["event_id"]},"MP3") is None
    assert playback_attempt_record({},"VOICE") is None


def test_ui_is_read_only_and_preserves_existing_live_voice_mechanism():
    terminal=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    ui=Path("trader/verified_signal_journal_ui.py").read_text("utf8")
    engine=Path("trader/verified_signal_journal.py").read_text("utf8")
    assert "render_signal_journal(" in terminal
    assert "playback_attempt_record(audio_event,used)" in terminal
    assert "render_voice_player(" in terminal
    assert 'st.audio(content,format=mime,autoplay=False)' in terminal
    assert "DZIENNIK SYGNAŁÓW LONG/SHORT" in ui
    assert "Sygnał workera (PL)" in ui
    assert "BRAK UDOKUMENTOWANEJ PRÓBY W TEJ SESJI" in ui
    for s in (ui,engine):
        assert "queue_paper(" not in s
        assert "CapitalReadOnly(" not in s
        assert "remote.save(" not in s
        assert "session.post(" not in s


def test_newest_event_still_visible_with_large_newest_first_checkpoint():
    # dump_state() reads recent_events newest-first; the UI must not use
    # events[-80:], which would pick the oldest and hide new alerts.
    latest=event(unique="latest",created="2026-11-19T13:00:00+00:00")
    historical=[
        event(unique=f"old-{i}",created="2026-11-19T11:49:01+00:00")
        for i in range(120)
    ]
    signals=verified_signal_rows(payload(events=[latest]+historical),limit=10)
    assert signals[0]["event_id"]==latest["event_id"]
    assert len(signals)==10
