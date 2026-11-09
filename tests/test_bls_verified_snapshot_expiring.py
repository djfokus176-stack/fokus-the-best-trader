"""Audited, time-limited macro backup: official BLS rechecked on 2026-11-08."""
from datetime import datetime,timedelta,timezone
import pytest
import requests
from trader.bls_verified_snapshot import (
    verified_schedule, VALID_UNTIL_UTC, SOURCE_URL, RESEARCH_VERIFIED_DATE)
from trader.news_radar import fetch_bls_schedule, macro_blackout
from trader.auto_news import refresh_news_state,calendar_is_current


class Resp:
    def __init__(self,status=403):
        self.status_code=status
        self.url="https://www.bls.gov/schedule"
        self.content=b"blocked"
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(f"{self.status_code}",response=self)


def reject(url,**kwargs):return Resp(403)


def test_snapshot_is_official_date_checked_and_uses_eastern_timezone():
    at=datetime(2026,11,6,20,30,tzinfo=timezone.utc)
    schedule=verified_schedule(now=at)
    assert schedule.source=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    assert schedule.source_url==SOURCE_URL=="https://www.bls.gov/schedule/2026/"
    assert RESEARCH_VERIFIED_DATE=="2026-11-08"
    assert len(schedule)==6
    dates={x["wydarzenie"]:x["data_utc"] for x in schedule}
    assert dates["Consumer Price Index for October 2026"]==datetime(
        2026,11,10,13,30,tzinfo=timezone.utc)
    assert dates["Producer Price Index for October 2026"]==datetime(
        2026,11,13,13,30,tzinfo=timezone.utc)
    assert dates["Employment Situation for October 2026"]==datetime(
        2026,11,6,13,30,tzinfo=timezone.utc)


def test_snapshot_blackout_20_mins_before_after_cpi():
    snapshot=verified_schedule(now=datetime(2026,11,6,21,tzinfo=timezone.utc))
    assert macro_blackout(snapshot,datetime(2026,11,10,13,15,tzinfo=timezone.utc))[0]
    assert macro_blackout(snapshot,datetime(2026,11,10,13,45,tzinfo=timezone.utc))[0]
    assert not macro_blackout(snapshot,datetime(2026,11,10,14,5,tzinfo=timezone.utc))[0]


def test_both_official_sources_403_use_only_short_lived_backup():
    at=datetime(2026,11,6,21,tzinfo=timezone.utc)
    calls=[]
    def get(url,**kw):
        calls.append(url)
        return Resp()
    cal=fetch_bls_schedule(get=get,now=at)
    assert len(calls)==2 # HTML requests stop at first HTTP403
    assert calls[0].startswith("https://www.bls.gov/")
    assert calls[1].startswith("https://www.bls.gov/")
    assert cal.source=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    assert cal.expires_utc==VALID_UNTIL_UTC.isoformat()


def test_legacy_backup_expires_but_checked_manual_fallback_is_separate():
    for at in [VALID_UNTIL_UTC,VALID_UNTIL_UTC+timedelta(hours=6)]:
        checked=fetch_bls_schedule(get=reject,now=at)
        assert checked.source=="BLS_VERIFIED_MANUAL_NOT_LIVE"
        assert checked.expires_utc=="2026-11-16T20:00:00+00:00"
    with pytest.raises(ValueError,match="BLS_MANUAL_VERIFICATION_EXPIRED"):
        fetch_bls_schedule(get=reject,now=datetime(2026,11,16,20,tzinfo=timezone.utc))


def test_no_backup_on_bls_500():
    with pytest.raises(requests.HTTPError) as exc:
        fetch_bls_schedule(get=lambda url,**kw:Resp(500),
            now=datetime(2026,11,6,21,tzinfo=timezone.utc))
    assert exc.value.response.status_code==500


def test_backup_invalid_outside_verification_window():
    with pytest.raises(ValueError,match="SNAPSHOT_EXPIRED"):
        verified_schedule(now=datetime(2026,11,5,23,59,tzinfo=timezone.utc))


def test_streamlit_cache_expires_even_if_last_fetch_was_recent():
    at=VALID_UNTIL_UTC-timedelta(minutes=5)
    state={}
    fetch=lambda:verified_schedule(now=at)
    refresh_news_state(state,now_mono=10,now_utc=at,fetch_news=lambda:([],{}),
        fetch_calendar=fetch)
    assert state["_calendar_source"]=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    assert calendar_is_current(state,now=at)
    assert not calendar_is_current(state,now=VALID_UNTIL_UTC)
    assert "calendar_source" not in state
    assert state["_calendar_expires_utc"]==VALID_UNTIL_UTC.isoformat()


def test_worker_logs_snapshot_source_and_expiry_without_changing_paper_gate():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    code=(root/"trader"/"worker.py").read_text(encoding="utf8")
    assert "MACRO_SOURCE=BLS_VERIFIED_SNAPSHOT_NOT_LIVE" in code
    assert "MACRO_BLACKOUT" in code
    assert 'if not reasons and verdict.action in ("LONG","SHORT")' in code
    app=(root/"app.py").read_text(encoding="utf8")
    assert "ZWERYFIKOWANA KOPIA, NIE LIVE" in app
