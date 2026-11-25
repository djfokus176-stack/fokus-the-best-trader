"""BLS availability/expiry regressions. Offline; no live trading or network."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from trader import news_radar, worker
from trader.manual_bls_calendar import load_verified_manual_bls

UTC = timezone.utc


def dt(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def denied(url, **kwargs):
    response = requests.Response()
    response.status_code = 403
    response.url = url
    response._content = b"Access denied"
    return response


def ok(url, body):
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response._content = body.encode()
    return response


def test_nov_dec_verified_backup_recovers_after_both_official_403():
    now = dt("2026-11-25T13:50:00+00:00")
    found = []
    def blocked(url, **kw):
        found.append(url)
        return denied(url, **kw)
    events = news_radar.fetch_bls_schedule(get=blocked, now=now)
    assert events.source == "BLS_VERIFIED_MANUAL_NOT_LIVE"
    assert len(events) >= 12
    assert found[0] == news_radar.BLS_ICS
    assert any("11_sched_list.htm" in x for x in found)
    # The HTML fallback deliberately stops after the first rejected month.
    assert dt(events.expires_utc) > now
    assert any(x["wydarzenie"] == "Consumer Price Index for November 2026"
               and x["data_utc"] == dt("2026-12-10T13:30:00+00:00")
               for x in events)
    blackout, _ = news_radar.macro_blackout(
        events, now=dt("2026-12-10T13:20:00+00:00"))
    assert blackout


def test_backup_expires_hard_and_never_opens_paper_after_expiry():
    expired = dt("2026-11-28T13:35:01+00:00")
    with pytest.raises(ValueError, match="BLS_MANUAL_VERIFICATION_EXPIRED"):
        news_radar.fetch_bls_schedule(get=denied, now=expired)
    with pytest.raises(ValueError, match="BLS_MANUAL_VERIFICATION_EXPIRED"):
        load_verified_manual_bls(now=expired)


def test_valid_official_ics_wins_without_ever_using_backup():
    now = dt("2026-11-17T12:55:00+00:00")
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Employment Situation
DTSTART;TZID=America/New_York:20261204T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART;TZID=America/New_York:20261210T083000
END:VEVENT
END:VCALENDAR"""
    seen = []
    def upstream(url, **kw):
        seen.append(url)
        return ok(url, ics)
    events = news_radar.fetch_bls_schedule(get=upstream, now=now)
    assert len(events) == 2
    assert seen == [news_radar.BLS_ICS]


def test_bad_http_200_ics_uses_official_html_before_backup():
    now = dt("2026-11-17T12:55:00+00:00")
    november = """<table>
<tr><th>Date</th><th>Time</th><th>Release</th></tr>
<tr><td>Friday, November 20, 2026</td><td>10:00 AM</td><td>Employment Situation Test</td></tr>
</table>"""
    december = """<table>
<tr><td>Friday, December 04, 2026</td><td>08:30 AM</td><td>Employment Situation for November</td></tr>
<tr><td>Thursday, December 10, 2026</td><td>08:30 AM</td><td>Consumer Price Index</td></tr>
</table>"""
    def upstream(url, **kw):
        if url == news_radar.BLS_ICS:
            return ok(url, "NOT A CALENDAR")
        if "11_sched_list.htm" in url:
            return ok(url, november)
        if "12_sched_list.htm" in url:
            return ok(url, december)
        raise AssertionError("Unexpected URL: "+url)
    events = news_radar.fetch_bls_schedule(get=upstream, now=now)
    assert type(events) is list  # Official HTML, not fallback
    assert len(events) == 3


def test_failed_bls_gate_rejects_long_without_queue(monkeypatch):
    """Even a perfect LONG cannot bypass macro gate after upstream failure."""
    import sqlite3
    from trader.mtf import TIMEFRAMES
    seen = dt("2026-11-17T12:30:00+00:00")
    snapshot = SimpleNamespace(
        good=True, frame=object(), spread=0.6,
        source="Capital.com DEMO REST", confirmed_utc=seen, reason="OK")
    client = SimpleNamespace(environment="DEMO", market_state=lambda epic: "TRADEABLE")
    decision = SimpleNamespace(action="LONG", reason="TEST LONG", strategy="EMA TREND",
                               entry=7420.0, stop=7415.0, target=7430.0, rr=2.0)
    view = SimpleNamespace(ready=True, timeframe="MINUTE", reason="OK")

    monkeypatch.setattr(worker, "fetch_all_timeframes",
                        lambda *a, **k: ({tf: snapshot for tf in TIMEFRAMES}, {}))
    monkeypatch.setattr(worker, "archive_candles", lambda *a, **k: 1)
    monkeypatch.setattr(worker, "progress_paper", lambda *a, **k: [])
    monkeypatch.setattr(worker, "evaluate_auto",
                        lambda *a, **k: (decision, []))
    monkeypatch.setattr(worker, "decide_any", lambda *a, **k: decision)
    monkeypatch.setattr(worker, "filter_mtf_decision",
                        lambda *a, **k: (decision, [view]))
    monkeypatch.setattr(worker, "current_feed_status",
                        lambda *a, **k: (True, "OK", None))
    monkeypatch.setattr(worker, "active_position", lambda *a, **k: None)
    def forbidden_queue(*a, **k):
        raise AssertionError("PAPER queue must remain closed")
    monkeypatch.setattr(worker, "queue_paper", forbidden_queue)

    def expired_calendar():
        raise ValueError("BLS_ALL_SOURCES_UNAVAILABLE__BLS_MANUAL_VERIFICATION_EXPIRED")

    with sqlite3.connect(":memory:") as db:
        result = worker.scan_once(
            client, "US500", "MINUTE", worker.AUTO_MODE, 2.0, db,
            calendar_fetch=expired_calendar, strict_macro=True)
    assert "LONG" in result
    assert "QUEUE=NO" in result
    assert "ACTIVE=NONE" in result
    assert "GATES=MACRO_CALENDAR_UNAVAILABLE" in result
    assert "BLS_MANUAL_VERIFICATION_EXPIRED" in result
