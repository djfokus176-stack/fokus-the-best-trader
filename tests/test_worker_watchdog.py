"""Watchdog must be read-only, fail stale, and never approve trading."""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from trader.worker_watchdog import (
    check_checkpoint_freshness, main, DEFAULT_MAX_AGE_MINUTES,
)


NOW=datetime(2026,11,16,15,0,0,tzinfo=timezone.utc)


def payload(last):
    return {"schema":1, "meta":{"last_scan_utc":last.isoformat()}}


def test_recent_checkpoint_is_only_a_heartbeat():
    p=payload(NOW-timedelta(minutes=1))
    r=check_checkpoint_freshness(7549,p,now=NOW)
    assert r["healthy"] is True
    assert r["status"]=="RECENT_CHECKPOINT"
    assert r["market_data_validated"] is False
    assert r["paper_entries_authorized"] is False
    assert r["checkpoint_version"]==7549
    assert r["age_seconds"]==60


def test_stale_checkpoint_is_failing_even_when_market_is_closed():
    p=payload(NOW-timedelta(minutes=9))
    r=check_checkpoint_freshness(7549,p,now=NOW)
    assert r["healthy"] is False
    assert r["status"]=="STALE_CHECKPOINT"
    assert r["paper_entries_authorized"] is False


def test_future_clock_and_missing_metadata_fail_closed():
    future=check_checkpoint_freshness(100,
        payload(NOW+timedelta(minutes=5)),now=NOW)
    assert future["status"]=="CLOCK_SKEW"
    assert future["healthy"] is False
    with pytest.raises(ValueError):
        check_checkpoint_freshness(100,{},now=NOW)
    with pytest.raises(ValueError):
        check_checkpoint_freshness(100,{"meta":{"last_scan_utc":"not a date"}},
                                  now=NOW)
    with pytest.raises(ValueError):
        check_checkpoint_freshness(100,{"meta":{"last_scan_utc":"2026-11-16 15:00:00"}},
                                  now=NOW)
    with pytest.raises(ValueError):
        check_checkpoint_freshness(-1,payload(NOW),now=NOW)


def test_threshold_is_limited_and_not_a_bypass():
    with pytest.raises(ValueError):
        check_checkpoint_freshness(1,payload(NOW),now=NOW,
                                   max_age_minutes=999999)
    with pytest.raises(ValueError):
        check_checkpoint_freshness(1,payload(NOW),now=NOW,
                                   max_age_minutes=0)


def test_separate_workflow_has_explicit_watchdog_opt_in_and_no_writer():
    root=Path(__file__).resolve().parents[1]
    workflow=(root/".github/workflows/fokus-checkpoint-watchdog.yml").read_text()
    assert "vars.FOKUS_WATCHDOG_ENABLED == 'true'" in workflow
    assert "python -m trader.worker_watchdog --max-age-minutes 8" in workflow
    assert "secrets.FOKUS_SUPABASE_SECRET_KEY" in workflow
    assert "python -m trader.worker --once" not in workflow
    assert "fokus-live_quotes" not in workflow


def test_failing_main_reports_only_sanitized_status(monkeypatch,capsys):
    class Checkpoint:
        @staticmethod
        def from_env():
            raise ValueError("bad credentials: avoid printing the secret")
    monkeypatch.setattr("trader.worker_watchdog.RemoteCheckpoint",Checkpoint)
    assert main([])==2
    out=capsys.readouterr().out
    assert "FOKUS_WATCHDOG=ERROR" in out
    assert "avoid printing" not in out
