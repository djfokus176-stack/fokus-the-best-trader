"""Cloud WAVE freshness checks are advisory and never authorize trading."""
from datetime import datetime, timezone

import pytest

from trader.research_readiness import assess_research_readiness


def test_weekend_is_not_false_wave_feed_failure():
    result=assess_research_readiness(
        {"last_scan_utc":"2026-11-15T13:58:00+00:00",
         "candle_backfill_enabled":True},
        {"last_closed_utc":"2026-11-13T21:45:00+00:00"},
        {"status":"NO_ELIGIBLE_GAP",
         "last_attempt_utc":"2026-11-15T13:50:00+00:00"},
        now=datetime(2026,11,15,14,0,tzinfo=timezone.utc))
    assert result["checkpoint_status"]=="SWIEZY CHECKPOINT"
    assert result["wave_ny_session"] is False
    assert result["wave_status"].startswith("POZA SESJA")
    assert result["backfill_status"]=="NO_ELIGIBLE_GAP"
    assert result["backfill_enabled"] is True
    assert result["trade_permission"]=="WAIT"
    assert result["quality_is_proven"] is False


def test_old_m15_in_ny_cash_session_requires_inspection():
    now="2026-11-16T15:05:00+00:00"  # 10:05 ET on Monday
    result=assess_research_readiness(
        {"last_scan_utc":"2026-11-16T15:04:00+00:00",
         "candle_backfill_enabled":"true"},
        {"last_closed_utc":"2026-11-13T21:45:00+00:00"},
        {"status":"NO_ELIGIBLE_GAP",
         "last_attempt_utc":"2026-11-16T14:50:00+00:00"},now=now)
    assert result["checkpoint_status"]=="SWIEZY CHECKPOINT"
    assert result["wave_ny_session"] is True
    assert result["wave_status"].startswith("STARA M15")
    assert result["trade_permission"]=="WAIT"


def test_recent_m15_does_not_establish_market_advantage():
    result=assess_research_readiness(
        {"last_scan_utc":"2026-11-16T14:59:00Z",
         "candle_backfill_enabled":True},
        {"last_closed_utc":"2026-11-16T14:45:00Z"}, {},
        now="2026-11-16T15:00:00Z")
    assert result["wave_status"]=="OSTATNIA M15 W ZAKRESIE KONTROLNYM"
    assert result["backfill_status"]=="WLACZONY — BRAK POTWIERDZONEJ PROBY"
    assert result["quality_is_proven"] is False
    assert result["trade_permission"]=="WAIT"


def test_stale_checkpoint_and_false_string_are_not_a_green_signal():
    result=assess_research_readiness(
        {"last_scan_utc":"2026-11-16T14:00:00Z",
         "candle_backfill_enabled":"false"},
        {"last_closed_utc":"2026-11-16T14:45:00Z"},
        {"status":"SUBMITTED_VERIFIED_CANDLES"},
        now="2026-11-16T15:00:00Z")
    assert result["checkpoint_status"].startswith("STARY CHECKPOINT")
    assert result["backfill_status"]=="WYLACZONY W CHECKPOINCIE"
    assert result["backfill_enabled"] is False
    assert result["trade_permission"]=="WAIT"


def test_missing_and_future_clock_do_not_claim_healthy():
    missing=assess_research_readiness({}, {}, {},now="2026-11-16T15:00:00Z")
    assert missing["checkpoint_status"]=="BRAK POTWIERDZONEGO CHECKPOINTU"
    assert missing["wave_status"]=="BRAK ZAPISANEJ M15"
    future=assess_research_readiness(
        {"last_scan_utc":"2026-11-16T16:00:00Z"},
        {"last_closed_utc":"2026-11-16T16:00:00Z"},{},
        now="2026-11-16T15:00:00Z")
    assert future["checkpoint_status"]=="NIEZGODNOSC ZEGAROW"
    assert future["wave_status"]=="NIEZGODNOSC ZEGAROW M15"
    assert future["trade_permission"]=="WAIT"


@pytest.mark.parametrize("now",["2026-11-16 15:00:00", "not-a-date"])
def test_unknown_observation_time_fails_closed(now):
    with pytest.raises(ValueError):
        assess_research_readiness({}, {}, {}, now=now)
