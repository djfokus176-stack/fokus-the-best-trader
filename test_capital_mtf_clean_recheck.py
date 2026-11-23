"""Fail-closed Capital.com MTF clean-tail recheck after bad long history.

Simulated snapshots only; no broker orders and no provider credentials.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from trader.market import FeedError
from trader.mtf import TIMEFRAMES, fetch_all_timeframes

NOW = datetime(2026, 11, 19, 16, 15, tzinfo=timezone.utc)
SOURCE = "Capital.com DEMO REST"


def snapshot(tf, *, good=True, reason="OK", source=SOURCE, epic="US500",
             time=NOW, size=90):
    return SimpleNamespace(good=good, reason=reason, source=source, epic=epic,
                           resolution=tf, confirmed_utc=time, frame=[0]*size)


def test_corrupt_long_history_can_recover_from_independently_valid_short_read():
    calls = []
    primary = snapshot("MINUTE_15", good=False,
                       reason="DANE_WADLIWE: odrzucono 253 rekordów")
    recovered = snapshot("MINUTE_15")
    class Client:
        def candles(self, epic, tf, *, count, max_spread):
            calls.append((epic, tf, count, max_spread))
            if tf == "MINUTE_15":
                return primary if count == 350 else recovered
            return snapshot(tf)
    items, failures = fetch_all_timeframes(Client(), "US500", count=350)
    assert not failures
    assert set(items) == set(TIMEFRAMES)
    assert items["MINUTE_15"].good
    assert "RECHECK_CLEAN_TAIL=96_AFTER_CORRUPT_HISTORY" in items["MINUTE_15"].reason
    assert [r[2] for r in calls if r[1] == "MINUTE_15"] == [350, 96]
    assert all(r[3] == 2.0 for r in calls)


def test_bad_current_prices_cannot_be_unblocked_by_another_bad_read():
    calls = []
    bad = snapshot("MINUTE_5", good=False, reason="DANE_WADLIWE: Wadliwa najnowsza świeca")
    class Client:
        def candles(self, epic, tf, *, count, max_spread):
            calls.append((tf, count))
            return bad if tf == "MINUTE_5" else snapshot(tf)
    items, failures = fetch_all_timeframes(Client(), "US500", count=350)
    assert not failures
    assert not items["MINUTE_5"].good
    assert [c for c in calls if c[0] == "MINUTE_5"] == [
        ("MINUTE_5", 350), ("MINUTE_5", 96)]


def test_untrusted_recheck_source_or_insufficient_candles_remains_blocked():
    for candidate in (
        snapshot("HOUR", source="other provider"),
        snapshot("HOUR", size=69),
        snapshot("HOUR", epic="XAUUSD"),
    ):
        bad = snapshot("HOUR", good=False,
                       reason="DANE_WADLIWE: history has crossed quotes")
        class Client:
            def candles(self, epic, tf, *, count, max_spread):
                if tf == "HOUR":
                    return bad if count == 350 else candidate
                return snapshot(tf)
        items, _ = fetch_all_timeframes(Client(), "US500", count=350)
        assert items["HOUR"] is bad
        assert not items["HOUR"].good


def test_unrelated_wait_does_not_trigger_extra_vendor_requests():
    calls = []
    class Client:
        def candles(self, epic, tf, *, count, max_spread):
            calls.append((tf, count))
            return snapshot(tf, good=False, reason="Spread przekracza limit")
    items, _ = fetch_all_timeframes(Client(), "US500", count=350)
    assert len(calls) == len(TIMEFRAMES)
    assert all(not s.good for s in items.values())


def test_recheck_network_failure_keeps_original_bad_snapshot():
    bad = snapshot("MINUTE_15", good=False,
                   reason="DANE_WADLIWE: brak serii 70")
    class Client:
        def candles(self, epic, tf, *, count, max_spread):
            if tf == "MINUTE_15":
                if count == 96:
                    raise FeedError("HTTP 429")
                return bad
            return snapshot(tf)
    items, failures = fetch_all_timeframes(Client(), "US500", count=350)
    assert not failures
    assert items["MINUTE_15"] is bad
    assert not items["MINUTE_15"].good
