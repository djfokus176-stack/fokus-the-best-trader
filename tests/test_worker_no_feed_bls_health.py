"""NO_FEED worker errors must not masquerade as a BLS verification failure.

These are read-only UI diagnostics; no worker entry gate is touched.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from trader.paper_health import worker_calendar_health, readiness_report


NOW=datetime(2026,11,9,17,40,tzinfo=timezone.utc)


def check(summary):
    return worker_calendar_health({
        "last_scan_utc":(NOW-timedelta(minutes=1)).isoformat(),
        "last_scan_summary":summary},now=NOW)


def test_no_feed_is_not_called_a_failed_bls_calendar():
    result=check("WAIT / NO_FEED / BROKER_STATUS=TRADEABLE / MINUTE: "
                 "Pobieranie swiec: HTTP 429")
    assert result["ok"] is False
    assert result["source"]=="NOT_CHECKED"
    assert "NO_FEED" in result["reason"]
    assert "HTTP 429" in result["reason"]
    assert "NIE sprawdził BLS" in result["reason"]


def test_other_early_exits_report_calendar_as_unchecked():
    for summary,expected in [
        ("WAIT / DATA_STALE / BRAK SWIEC", "DATA_STALE"),
        ("WAIT / MARKET_CLOSED / BROKER_STATUS=CLOSED", "zamknięty")]:
        result=check(summary)
        assert result["ok"] is False
        assert result["source"]=="NOT_CHECKED"
        assert expected in result["reason"]


def test_valid_bls_calendar_still_requires_gates_ok():
    success=check("2026-11-09T17:39:00+00:00 / WAIT / "
                  "GATES=OK / DIAGNOSTICS=MACRO_SOURCE="
                  "BLS_VERIFIED_SNAPSHOT_NOT_LIVE;"
                  "EXPIRES_UTC=2026-11-10T00:00:00+00:00")
    assert success["ok"] is True
    assert success["source"]=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    blocked=check("2026-11-09T17:39:00+00:00 / WAIT / "
                  "GATES=MACRO_CALENDAR_UNAVAILABLE")
    assert blocked["ok"] is False
    assert blocked["source"]=="BRAK"


def test_no_feed_remains_real_readiness_block_not_green_by_age_alone():
    m=check("WAIT / NO_FEED / BROKER_STATUS=TRADEABLE / MINUTE: HTTP 429")
    readiness=readiness_report(
        clock_verified=True,data_ready=True,market_status="TRADEABLE",
        mtf_ready=True,calendar_current=m["ok"],remote_view=True,
        worker_age=60,calendar_scope="worker",calendar_reason=m["reason"])
    assert readiness["ready_to_consider_setup"] is False
    assert len(readiness["blockers"])==1
    assert "NIE sprawdził BLS" in readiness["blockers"][0]


def test_readiness_ui_exposes_exact_sanitized_worker_error():
    s=(Path(__file__).resolve().parents[1]/"app.py").read_text("utf-8")
    assert "worker_summary[:350]" in s
    assert "HTTP 429" in s and "HTTP 401" in s and "HTTP 404" in s
    assert "NIE pobrał świec M1" in s
    assert "No secrets" not in s or "CAPITAL_PASSWORD" not in s
