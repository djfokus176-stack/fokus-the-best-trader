"""Freshness checks for a persistent dashboard."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from trader.runtime import current_feed_status, scan_delay_seconds

def fake(now, secs_ago=45, good=True, tf='MINUTE'):
    return SimpleNamespace(confirmed_utc=now-timedelta(seconds=secs_ago),
        resolution=tf, good=good, age_seconds=secs_ago, reason='OK' if good else 'feed error')

def test_current_feed_expires_after_time_passes():
    now=datetime(2026,11,4,21,50,tzinfo=timezone.utc)
    snap=fake(now,60)
    assert current_feed_status(snap,'Capital.com DEMO REST',now)[0] is True
    assert current_feed_status(snap,'Capital.com DEMO REST',now+timedelta(minutes=5))[0] is False

def test_real_feed_allowed_read_only():
    now=datetime(2026,11,4,21,50,tzinfo=timezone.utc)
    assert current_feed_status(fake(now),'Capital.com LIVE REST',now)[0] is True

def test_csv_is_not_live():
    now=datetime(2026,11,4,21,50,tzinfo=timezone.utc)
    assert current_feed_status(fake(now),'CSV NAUKA (NIE LIVE)',now)[0] is False

def test_stale_bad_snapshot_never_ready():
    now=datetime(2026,11,4,21,50,tzinfo=timezone.utc)
    assert current_feed_status(fake(now,good=False),'Capital.com DEMO REST',now)[0] is False

def test_manual_refresh_options():
    assert [scan_delay_seconds(i) for i in (5,15,30,60,120,300)] == [5,15,30,60,120,300]
    import pytest
    for x in (0,1,10,31,61,600):
        with pytest.raises(ValueError):
            scan_delay_seconds(x)
