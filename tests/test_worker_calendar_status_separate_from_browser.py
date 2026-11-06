"""Remote dashboard must not confuse local BLS 403 with worker readiness."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from trader.paper_health import (
    worker_calendar_health, readiness_report
)

NOW=datetime(2026,11,6,20,40,tzinfo=timezone.utc)
def meta(*, summary, age_seconds=20):
    return {"last_scan_utc":(NOW-timedelta(seconds=age_seconds)).isoformat(),
            "last_scan_summary":summary}

GOOD=("2026-11-06T20:33:00+00:00 / WAIT / QUEUE=NO / "
      "GATES=OK / DIAGNOSTICS=MACRO_SOURCE=BLS_VERIFIED_SNAPSHOT_NOT_LIVE;"
      "EXPIRES_UTC=2026-11-08T00:00:00+00:00 / "
      "Po filtrach MTF zgodnych setupów 0/2")


def test_checkpoints_reproduce_real_case_9_without_fake_live_calendar():
    health=worker_calendar_health(meta(summary=GOOD),now=NOW)
    assert health["ok"] is True
    assert health["source"]=="BLS_VERIFIED_SNAPSHOT_NOT_LIVE"
    assert health["expires"]=="2026-11-08T00:00:00+00:00"
    report=readiness_report(clock_verified=True,data_ready=True,
        market_status="TRADEABLE",mtf_ready=True,
        calendar_current=health["ok"],calendar_scope="worker",
        calendar_reason=health["reason"],remote_view=True,worker_age=20)
    assert not report["blockers"]
    assert any(c["kontrola"].startswith("Kalendarz BLS (worker") and
               c["status"]=="✅ OK" for c in report["checks"])


def test_expired_bls_backup_never_shows_worker_ready():
    health=worker_calendar_health(meta(summary=GOOD),
         now=datetime(2026,11,8,0,0,tzinfo=timezone.utc))
    assert health["ok"] is False


def test_expired_backup_in_fresh_worker_checkpoint_is_not_accepted():
    future=datetime(2026,11,8,0,1,tzinfo=timezone.utc)
    checkpoint={"last_scan_utc":(future-timedelta(seconds=10)).isoformat(),
      "last_scan_summary":GOOD}
    assert not worker_calendar_health(checkpoint,now=future)["ok"]


def test_reject_stale_or_future_checkpoint():
    assert not worker_calendar_health(meta(summary=GOOD,age_seconds=901),now=NOW)["ok"]
    assert not worker_calendar_health(meta(summary=GOOD,age_seconds=-4),now=NOW)["ok"]


def test_reject_missing_source_or_expiry_even_with_gates_ok():
    variants=["WAIT / GATES=OK / DIAGNOSTICS=BLANK",
              "WAIT / GATES=OK / DIAGNOSTICS=MACRO_SOURCE=BLS_VERIFIED_SNAPSHOT_NOT_LIVE",
              "WAIT / GATES=OK / DIAGNOSTICS=MACRO_SOURCE=BLS_VERIFIED_SNAPSHOT_NOT_LIVE;EXPIRES_UTC=not-a-date"]
    for text in variants:
        assert not worker_calendar_health(meta(summary=text),now=NOW)["ok"]


def test_reject_unsafe_gate_even_if_source_is_fresh():
    for gate in ("MACRO_CALENDAR_UNAVAILABLE","MACRO_BLACKOUT","DATA_STALE"):
        summary=GOOD.replace("GATES=OK","GATES="+gate)
        assert not worker_calendar_health(meta(summary=summary),now=NOW)["ok"]


def test_official_live_source_is_accepted_only_from_fresh_successful_worker():
    health=worker_calendar_health(meta(
        summary="WAIT / GATES=OK / DIAGNOSTICS=MACRO_SOURCE=BLS_OFFICIAL_LIVE / ..." ),
        now=NOW)
    assert health["ok"] and health["source"]=="BLS_OFFICIAL_LIVE"
    assert not worker_calendar_health(meta(
        summary="WAIT / GATES=OKAY / DIAGNOSTICS=MACRO_SOURCE=BLS_OFFICIAL_LIVE"),
        now=NOW)["ok"]


def test_local_browser_and_remote_worker_are_separate():
    local=readiness_report(clock_verified=True,data_ready=True,
        market_status="TRADEABLE",mtf_ready=True,calendar_current=False,
        remote_view=False)
    assert len(local["blockers"])==1
    assert "sesja Streamlit" in local["checks"][4]["kontrola"]
    text=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf8")
    assert "calendar_current=(worker_calendar['ok'] if remote_is_on" in text
    assert "if not local_calendar_ok:" in text
    assert "Nie blokuje to osobnego workera PAPER" in text
    assert "Lokalna analiza nadal ma WAIT bez kalendarza" in text
