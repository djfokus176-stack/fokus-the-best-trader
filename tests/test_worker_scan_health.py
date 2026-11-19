"""Worker health monitoring regression: a green heartbeat is not enough."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trader.worker_scan_health import (
    classify_scan_status, advance_scan_quality, PERSISTENT_FAULT_SCANS,
)
from trader.worker_watchdog import check_checkpoint_freshness

NOW = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)


def checkpoint(quality, stamp=None):
    return {"schema":1, "meta":{
        "last_scan_utc":(stamp or NOW-timedelta(minutes=1)).isoformat(),
        "scan_quality":quality,
    }}


def test_normal_wait_is_not_a_bug_or_veto():
    msg = "2026-11-19T19:59:00+00:00 / WAIT / CANDIDATE_METHOD=WAIT / GATES=OK / no pattern"
    state, code, fault = classify_scan_status(msg)
    assert (state,code,fault) == ("OK","OK",False)
    q=advance_scan_quality(msg,{"consecutive_fault_scans":7},now=NOW)
    assert q["consecutive_fault_scans"] == 0
    assert check_checkpoint_freshness(10,checkpoint(q),now=NOW)["healthy"]


def test_persistent_mtf_failure_is_alerted_despite_fresh_checkpoint():
    bad = "2026-11-19T19:59:00+00:00 / WAIT / GATES=INCOMPLETE_MTF / HOUR:BAD_SNAPSHOT"
    q=None
    for i in range(PERSISTENT_FAULT_SCANS):
        q=advance_scan_quality(bad,q,now=NOW+timedelta(minutes=i))
    assert q["consecutive_fault_scans"] == PERSISTENT_FAULT_SCANS
    assert q["persistent_fault"] is True
    assert q["code"] == "INCOMPLETE_MTF"
    r=check_checkpoint_freshness(90,checkpoint(q),now=NOW)
    assert r["status"] == "PERSISTENT_SCAN_BLOCKER"
    assert r["healthy"] is False
    assert r["scan_code"] == "INCOMPLETE_MTF"
    assert r["paper_entries_authorized"] is False
    assert r["market_data_validated"] is False


def test_transient_mtf_failure_does_not_trigger_false_alarm():
    bad="2026-11-19T19:59:00+00:00 / WAIT / GATES=INCOMPLETE_MTF"
    q=advance_scan_quality(bad,None,now=NOW)
    r=check_checkpoint_freshness(3,checkpoint(q),now=NOW)
    assert r["status"]=="RECENT_CHECKPOINT"
    assert r["healthy"] is True
    assert r["consecutive_fault_scans"]==1


def test_good_scan_resets_fault_streak_and_risk_pause_does_not_bypass_stop():
    bad="WAIT / DATA_STALE / bad M1"
    q=None
    for _ in range(12):
        q=advance_scan_quality(bad,q,now=NOW)
    assert q["persistent_fault"]
    risk="2026-11-19T19:59:00+00:00 / WAIT / GATES=PAPER_DAILY_DRAWDOWN_LIMIT"
    q=advance_scan_quality(risk,q,now=NOW)
    assert q["state"]=="PAUSED_RISK"
    assert q["code"]=="PAPER_DAILY_DRAWDOWN_LIMIT"
    assert not q["persistent_fault"]
    assert q["consecutive_fault_scans"] == 0


def test_known_market_closure_macro_blackout_and_setup_disabled_not_errors():
    samples=(
        ("WAIT / MARKET_CLOSED / BROKER_STATUS=CLOSED", "MARKET_CLOSED"),
        ("WAIT / GATES=MACRO_BLACKOUT", "PAUSED_MACRO"),
        ("WAIT / GATES=SETUPS_DISABLED", "PAUSED_CONFIG"),
    )
    for msg,state in samples:
        q=advance_scan_quality(msg,{"consecutive_fault_scans":99},now=NOW)
        assert q["state"]==state
        assert not q["persistent_fault"]
        assert check_checkpoint_freshness(7,checkpoint(q),now=NOW)["healthy"]


def test_unknown_and_bls_failure_fail_closed_after_streak():
    for msg in ("WAIT / unexpected format", "WAIT / GATES=MACRO_CALENDAR_UNAVAILABLE"):
        q=None
        for _ in range(PERSISTENT_FAULT_SCANS):
            q=advance_scan_quality(msg,q,now=NOW)
        assert not check_checkpoint_freshness(4,checkpoint(q),now=NOW)["healthy"]


def test_old_checkpoint_and_bad_metadata_cannot_claim_trading_ready():
    old={"schema":1,"meta":{"last_scan_utc":NOW.isoformat()}}
    r=check_checkpoint_freshness(3,old,now=NOW)
    assert r["healthy"] is True  # legacy heartbeat only
    assert r["market_data_validated"] is False
    q={"state":"FAULT","code":"secret:unsafe","consecutive_fault_scans":"8"}
    r=check_checkpoint_freshness(4,checkpoint(q),now=NOW)
    assert r["scan_code"]=="UNKNOWN"
    assert r["consecutive_fault_scans"]==0


def test_worker_writes_scan_quality_into_durable_metadata_only():
    root=Path(__file__).resolve().parents[1]
    src=(root/"trader"/"worker.py").read_text(encoding="utf-8")
    assert 'old_quality=(old_meta.get("scan_quality")' in src
    assert '"scan_quality":advance_scan_quality(status,old_quality)' in src
    assert "PERSISTENT_FAULT_SCANS" not in src
