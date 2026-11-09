"""Manual BLS backup: source-verified, explicit expiry, no gate bypass or fake dates."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from trader.manual_bls_calendar import load_verified_manual_bls, DEFAULT_CALENDAR_FILE
from trader.news_radar import macro_blackout
from trader.paper_health import worker_calendar_health


VERIFIED = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)


def test_official_manual_has_real_utc_schedule_and_blackout():
    cal=load_verified_manual_bls(now=VERIFIED+timedelta(hours=1))
    assert cal.source=="BLS_VERIFIED_MANUAL_NOT_LIVE"
    assert len(cal)==21 and cal.expires_utc==EXPIRES.isoformat()
    by_title={x["wydarzenie"]:x["data_utc"] for x in cal}
    assert by_title["Consumer Price Index for October 2026"]==datetime(
        2026,11,10,13,30,tzinfo=timezone.utc)
    assert by_title["Employment Situation for November 2026"]==datetime(
        2026,12,4,13,30,tzinfo=timezone.utc)
    assert macro_blackout(cal,now=datetime(2026,11,10,13,18,tzinfo=timezone.utc))[0]


def test_manual_absent_or_tampered_never_unlocks(tmp_path):
    missing=tmp_path/"missing.json"
    with pytest.raises(ValueError,match="FILE_MISSING"):
        load_verified_manual_bls(now=VERIFIED,path=missing)
    doc=json.loads(DEFAULT_CALENDAR_FILE.read_text(encoding="utf-8"))
    variants=[
        ("source","THIRD_PARTY_SCHEDULE"),
        ("source_urls",["https://random.example/calendar"]),
        ("valid_until_utc","2026-12-21T20:00:00+00:00"),
        ("events",[]),
        ("timezone","UTC"),
    ]
    for field,value in variants:
        changed={**doc,field:value}
        path=tmp_path/f"{field}.json"
        path.write_text(json.dumps(changed),encoding="utf-8")
        with pytest.raises(ValueError):
            load_verified_manual_bls(now=VERIFIED,path=path)


def test_expiry_never_rolls_forward_and_requires_timezone():
    with pytest.raises(ValueError,match="VERIFICATION_EXPIRED"):
        load_verified_manual_bls(now=EXPIRES)
    with pytest.raises(ValueError,match="VERIFICATION_EXPIRED"):
        load_verified_manual_bls(now=VERIFIED-timedelta(seconds=1))
    with pytest.raises(ValueError,match="TIMEZONE_UNVERIFIED"):
        load_verified_manual_bls(now=datetime(2026,11,10,12,0))


def test_worker_health_recognizes_manual_not_live_and_48h_warning_in_app():
    cal=load_verified_manual_bls(now=VERIFIED)
    meta={"last_scan_utc":(EXPIRES-timedelta(hours=47)).isoformat(),
          "last_scan_summary":(
              "2026-11-14T20:00:00+00:00 / WAIT / GATES=OK / "
              "DIAGNOSTICS=MACRO_SOURCE=BLS_VERIFIED_MANUAL_NOT_LIVE;"
              f"EXPIRES_UTC={cal.expires_utc}")}
    result=worker_calendar_health(meta,now=EXPIRES-timedelta(hours=47))
    assert result["ok"] and result["source"]=="BLS_VERIFIED_MANUAL_NOT_LIVE"
    assert result["expires"]==cal.expires_utc
    expired=worker_calendar_health(meta,now=EXPIRES)
    assert expired["ok"] is False
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "timedelta(hours=48)" in app
    worker=(Path(__file__).resolve().parents[1]/"trader"/"worker.py").read_text(encoding="utf-8")
    assert "BLS_VERIFIED_MANUAL_NOT_LIVE" in worker
