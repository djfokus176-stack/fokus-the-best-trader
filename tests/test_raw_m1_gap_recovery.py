"""RAW M1 gap recovery: replay REAL closed bars a skipped scan left behind.

Synthetic prices below are test fixtures only. Production never synthesizes
candles; these tests check that the state machine uses bars that are present
in the snapshot, in chronological order, and never invents a fill or an exit.
"""
import pandas as pd

from trader.raw_m1_forward_paper import (
    advance_raw_paper, raw_paper_report, MAX_RECOVER_BARS,
)


def candles(count=95, *, side="LONG"):
    index = pd.date_range("2026-11-17T19:00:00Z", periods=count, freq="min")
    prices = [7400 + (i * .10 if side == "LONG" else -i * .10) for i in range(count)]
    return pd.DataFrame({
        "Open": prices, "High": [v + 1.2 for v in prices],
        "Low": [v - 1.2 for v in prices], "Close": prices,
        "Spread": [.4] * count}, index=index)


def votes(side="LONG"):
    return [{"Strategia": "EMA TREND", "Setup OHLC": side,
             "Po filtrze MTF": "WAIT", "Powód": "MTF veto"}]


def opened_state():
    """Setup at bar 94, filled at bar 95 (OPEN) without any gap."""
    first = advance_raw_paper({}, candles(), votes(), spread=.4)
    return advance_raw_paper(first, candles(96), votes(), spread=.4)


def test_open_position_survives_skipped_scan_and_closes_on_real_sl_bar():
    opened = opened_state()
    assert opened["active"]["status"] == "OPEN"
    snap = candles(110)
    # Scanner skipped minutes 96..; the 350-bar snapshot still contains them.
    snap.iloc[101, snap.columns.get_loc("Low")] = 7000.0  # real SL hit at bar 101
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["invalidated"] == 0
    assert state["active"] is None
    assert len(state["closed"]) == 1
    closed = state["closed"][-1]
    assert closed["status"] == "CLOSED_SL"
    assert closed["closed_utc"] == snap.index[101].isoformat()
    assert state["gaps_recovered"] == 1
    assert state["recovered_bars"] == 6  # minutes 96..101 replayed up to the close
    assert state["last_candle_utc"] == snap.index[-1].isoformat()


def test_chronology_first_hit_wins_within_recovered_range():
    opened = opened_state()
    snap = candles(110)
    snap.iloc[98, snap.columns.get_loc("High")] = 7500.0  # TP first (bar 98)
    snap.iloc[101, snap.columns.get_loc("Low")] = 7000.0  # SL later (bar 101)
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    closed = state["closed"][-1]
    assert closed["status"] == "CLOSED_TP"
    assert closed["closed_utc"] == snap.index[98].isoformat()


def test_pending_fill_bar_inside_gap_is_recovered_not_invalidated():
    first = advance_raw_paper({}, candles(), votes(), spread=.4)
    assert first["active"]["status"] == "PENDING"
    snap = candles(97)  # minutes 95 and 96 both present, scanner skipped them
    state = advance_raw_paper(first, snap, votes(), spread=.4)
    assert state["invalidated"] == 0
    assert state["opened"] == 1
    assert state["active"]["status"] == "OPEN"
    assert state["active"]["entry_bar_open_utc"] == snap.index[94].isoformat()
    assert state["active"]["opened_utc"] == snap.index[95].isoformat()


def test_real_hole_still_invalidates_and_never_invents_bars():
    opened = opened_state()
    snap = candles(110)
    snap = snap.drop(snap.index[99])  # genuine missing minute
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["active"] is None
    assert state["invalidated_after_open_total"] == 1
    assert state["invalidated_rows"][-1]["invalidation_reason"] == "MISSING_M1_BAR"
    assert state["closed"] == []
    assert state.get("gaps_recovered", 0) == 0


def test_outage_longer_than_limit_is_not_recovered():
    opened = opened_state()
    snap = candles(95 + MAX_RECOVER_BARS + 5)
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["active"] is None
    assert state["invalidated_after_open_total"] == 1
    assert state.get("gaps_recovered", 0) == 0


def test_recovered_tick_never_opens_hindsight_setup():
    first = advance_raw_paper({}, candles(), votes(), spread=.4)
    first["active"] = None  # no open lane; only a gap to recover
    state = advance_raw_paper(first, candles(99), votes(), spread=.4)
    assert state["started"] == first["started"]
    assert state["active"] is None
    assert state["gaps_recovered"] == 1


def test_corrupt_recovered_bar_invalidates_without_fake_exit():
    opened = opened_state()
    snap = candles(110)
    snap.iloc[97, snap.columns.get_loc("Close")] = 1e5  # close outside H/L
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["active"] is None
    assert state["invalidated_rows"][-1]["invalidation_reason"] == "INVALID_FILL_OR_CANDLE"
    assert state["closed"] == []


def test_replaying_same_snapshot_is_idempotent():
    opened = opened_state()
    snap = candles(110)
    snap.iloc[101, snap.columns.get_loc("Low")] = 7000.0
    once = advance_raw_paper(opened, snap, votes(), spread=.4)
    twice = advance_raw_paper(once, snap, votes(), spread=.4)
    assert once["closed"] == twice["closed"]
    assert twice["closed_total"] == 1
    assert twice["opened"] == once["opened"]


def test_report_exposes_recovery_counters_and_no_pnl_for_invalidated():
    opened = opened_state()
    snap = candles(110).drop(candles(110).index[99])
    report = raw_paper_report(advance_raw_paper(opened, snap, votes(), spread=.4))
    assert report["gaps_recovered"] == 0
    assert report["invalidated_after_open"] == 1
    assert report["recovered_bars"] == 0


def test_hole_inside_recent_window_invalidates_immediately_not_frozen():
    """Regression: a hole in the last 10 bars used to freeze the position
    (early return) until the hole left the window, unlike a real SL/TP."""
    opened = opened_state()
    snap = candles(110).drop(candles(110).index[107])  # hole in last 10 bars
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["active"] is None
    assert state["invalidated_after_open_total"] == 1
    assert state["last_candle_utc"] == snap.index[-1].isoformat()


def test_hole_on_normal_step_still_blocks_indicator_computation():
    """No gap jump -> strict contiguity: a broken recent window is refused."""
    opened = opened_state()
    snap = candles(96)  # prior bar 95 is the newest processed bar
    snap = snap.drop(snap.index[93])  # hole before the newest bars
    state = advance_raw_paper(opened, snap, votes(), spread=.4)
    assert state["last_reason"] == "NIEWIARYGODNE_ZAMKNIETE_M1_RAW"
    assert state["active"]["status"] == "OPEN"
    assert state.get("gaps_recovered", 0) == 0
