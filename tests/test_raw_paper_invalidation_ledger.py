"""RAW PAPER: keep every unresolvable position visible, never invent P&L."""
import pandas as pd

from trader.raw_m1_forward_paper import advance_raw_paper,raw_paper_report,blank
from trader.raw_paper_chart import rows_for_journal


def candles(count=95, *, side="LONG"):
    index=pd.date_range("2026-11-17T19:00:00Z",periods=count,freq="min")
    prices=[7400+(i*.10 if side=="LONG" else -i*.10) for i in range(count)]
    return pd.DataFrame({
        "Open":prices,
        "High":[v+1.2 for v in prices],
        "Low":[v-1.2 for v in prices],
        "Close":prices,"Spread":[.4]*count},index=index)


def votes(side="LONG"):
    return [{"Strategia":"EMA TREND","Setup OHLC":side,
             "Po filtrze MTF":"WAIT","Powód":"MTF veto"}]


def test_pending_invalidated_by_missing_minute_logged_without_fake_open_or_result():
    pending=advance_raw_paper({},candles(),votes(),spread=.4)
    # Real hole: minute 95 is absent from the snapshot.
    missing=advance_raw_paper(pending,candles(97).drop(candles(97).index[95]),votes(),spread=.4)
    assert missing["opened"]==0
    assert missing["invalidated_before_open_total"]==1
    assert missing["invalidated_after_open_total"]==0
    assert missing["invalidated_rows"][-1]["previous_status"]=="PENDING"
    assert missing["invalidated_rows"][-1]["pnl_pts"] is None
    report=raw_paper_report(missing)
    assert report["invalidated_before_open"]==1
    assert report["unreconciled_historical_open"]==0
    journal=rows_for_journal(report)
    assert journal[0]["Status"]=="INVALIDATED"
    assert journal[0]["Wejście (pkt)"] is None
    assert journal[0]["Zysk/strata netto (pkt)"] is None
    assert journal[0]["Powód"]=="MISSING_M1_BAR"


def test_open_invalidated_by_gap_is_logged_and_reconciled_without_pnl():
    first=advance_raw_paper({},candles(),votes(),spread=.4)
    opened=advance_raw_paper(first,candles(96),votes(),spread=.4)
    assert opened["opened"]==1 and opened["active"]["status"]=="OPEN"
    # Real hole: minute 96 is absent from the snapshot.
    gap=advance_raw_paper(opened,candles(98).drop(candles(98).index[96]),votes(),spread=.4)
    assert gap["opened"]==1
    assert gap["closed"]==[]
    assert gap["active"] is None
    assert gap["invalidated_after_open_total"]==1
    event=gap["invalidated_rows"][-1]
    assert event["previous_status"]=="OPEN"
    assert event["side"]=="LONG"
    assert event["setup_utc"]==first["active"]["setup_utc"]
    assert event["opened_utc"]==opened["active"]["opened_utc"]
    assert event["invalidation_reason"]=="MISSING_M1_BAR"
    assert event["closed_utc"] is None and event["pnl_pts"] is None
    report=raw_paper_report(gap)
    assert report["opened"]==1 and report["closed"]==0
    assert report["invalidated_after_open"]==1
    assert report["unreconciled_historical_open"]==0
    row=rows_for_journal(report)[0]
    assert row["Status"]=="INVALIDATED"
    assert row["Kierunek"]=="LONG"
    assert row["CLOSE (Polska)"]=="—"
    assert row["Unieważniono (Polska)"]!="—"
    assert row["Wejście (pkt)"]==opened["active"]["entry_mid"]
    assert row["Wyjście (pkt)"] is None
    assert row["Zysk/strata netto (pkt)"] is None
    repeat=advance_raw_paper(gap,candles(98).drop(candles(98).index[96]),votes(),spread=.4)
    assert repeat["invalidated_after_open_total"]==1
    assert len(repeat["invalidated_rows"])==1


def test_legacy_open_minus_closed_is_explicit_unknown_not_assigned_gains_or_losses():
    old=blank()
    for key in ("invalidated_after_open_total","invalidated_before_open_total",
                "invalidated_rows","closed_total"):
        old.pop(key)
    old.update(
        started=15,opened=10,active=None,invalidated=7,closed=[
            {"status":"CLOSED_TP","pnl_pts":9.289,"side":"LONG"},
            {"status":"CLOSED_SL","pnl_pts":-6.92,"side":"SHORT"},
            {"status":"CLOSED_TP","pnl_pts":8.25,"side":"SHORT"},
        ])
    report=raw_paper_report(old)
    assert report["opened"]==10
    assert report["closed"]==3
    assert report["unreconciled_historical_open"]==7
    assert report["pnl_pts"]==round(9.289-6.92+8.25,2)
    assert report["invalidated_recent"]==[]


def test_same_minute_close_keeps_open_and_pnl_and_does_not_invalidate():
    first=advance_raw_paper({},candles(),votes(),spread=.4)
    c=candles(96)
    c.iloc[-1,c.columns.get_loc("High")]=first["active"]["target"]+.25
    c.iloc[-1,c.columns.get_loc("Low")]=first["active"]["stop"]+.1
    done=advance_raw_paper(first,c,votes(),spread=.4)
    assert done["opened"]==1 and done["closed_total"]==1
    assert done["invalidated_after_open_total"]==0
    assert raw_paper_report(done)["unreconciled_historical_open"]==0


def test_invalid_fill_logs_unverified_pending_without_open_or_pnl():
    first=advance_raw_paper({},candles(),votes(),spread=.4)
    c=candles(96)
    c.iloc[-1,c.columns.get_loc("Open")]=first["active"]["target"]+2
    c.iloc[-1,c.columns.get_loc("High")]=c.iloc[-1]["Open"]+1
    c.iloc[-1,c.columns.get_loc("Low")]=c.iloc[-1]["Open"]-1
    c.iloc[-1,c.columns.get_loc("Close")]=c.iloc[-1]["Open"]
    gone=advance_raw_paper(first,c,votes(),spread=.4)
    assert gone["opened"]==0
    assert gone["invalidated_before_open_total"]==1
    assert gone["invalidated_rows"][-1]["invalidation_reason"]=="INVALID_FILL_OR_CANDLE"
    assert gone["invalidated_rows"][-1]["pnl_pts"] is None
