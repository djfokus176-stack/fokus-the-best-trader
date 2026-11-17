"""CLOUD chart diagnostics: counts are ledger-based, not plot-based.

Never invent entries when the marker is cropped, the database is missing,
or a PAPER setup has not reached OPEN.
"""
import pandas as pd
import pytest
from pathlib import Path

from trader.cloud_paper_visibility import cloud_paper_visibility, cloud_chart_gaps
from trader.cloud_paper_terminal import cloud_chart_view_range


META={"epic":"US500","source":"Capital.com DEMO REST"}


def pos(trade_id,status,side="SHORT",opened=None,closed=None):
    return {"trade_id":trade_id,"status":status,"side":side,
            "epic":"US500","source":"Capital.com DEMO REST",
            "opened_utc":opened,"closed_utc":closed}


def test_counts_real_ledger_even_if_zoom_shows_only_one_entry():
    payload={"meta":META,"tables":{"paper_positions_v3":[
        pos("a","CLOSED_TP","SHORT","2026-11-17T14:00:00Z",
            "2026-11-17T14:10:00Z"),
        pos("b","CLOSED_SL","LONG","2026-11-17T16:00:00Z",
            "2026-11-17T16:12:00Z"),
        pos("c","OPEN","LONG","2026-11-17T17:50:00Z"),
        pos("d","PENDING","SHORT"),
        pos("e","INVALIDATED","LONG"),
    ]}}
    a=cloud_paper_visibility(payload,viewport=[
        "2026-11-17T17:40:00Z","2026-11-17T18:00:00Z"])
    assert a["known"]
    assert a["total_open"]==3
    assert a["total_closed"]==2
    assert a["pending"]==1
    assert a["invalidated"]==1
    assert a["active_open"]==1
    assert a["visible_open"]==1
    assert a["visible_closed"]==0
    assert a["last_open_utc"]=="2026-11-17T17:50:00+00:00"
    assert a["last_close_utc"]=="2026-11-17T16:12:00+00:00"


def test_history_missing_or_wrong_market_fails_closed():
    for data in (None,{},{"meta":META}, {"meta":META,"tables":{}},
                 {"meta":{"epic":"GER40","source":"Capital.com DEMO REST"},
                  "tables":{"paper_positions_v3":[]}}):
        a=cloud_paper_visibility(data)
        assert a["known"] is False
        assert a["total_open"]==0
    data={"meta":META,"tables":{"paper_positions_v3":[
        pos("x","PENDING"),pos("bad","OPEN",side="UNKNOWN"),
        pos("mal","CLOSED_TP",opened=None,closed=None)]}}
    b=cloud_paper_visibility(data)
    assert b["pending"]==1
    assert b["invalid_rows"]==1
    assert b["total_open"]==0 and b["total_closed"]==0


def test_zoom_30_is_more_readable_and_does_not_create_candles():
    idx=pd.date_range("2026-11-17T12:00:00Z",periods=180,freq="min")
    f=pd.DataFrame({"Close":[7400.0]*180},index=idx)
    a,b=cloud_chart_view_range(f,"M1",visible_count=30)
    assert a==idx[-30] and b==idx[-1]+pd.Timedelta(minutes=2)
    with pytest.raises(ValueError):
        cloud_chart_view_range(f,"M1",visible_count=5)


def test_gap_flags_only_observed_missing_time_slots_not_synthetic_bars():
    times=pd.to_datetime(["2026-11-17T15:01:00Z",
                          "2026-11-17T15:02:00Z",
                          "2026-11-17T15:06:00Z",
                          "2026-11-17T15:07:00Z"])
    f=pd.DataFrame({"Close":[1.,2.,3.,4.]},index=times)
    a=cloud_chart_gaps(f,"M1",visible_count=20)
    assert a["bars"]==4
    assert a["gaps"]==1
    assert a["missing_slots"]==3
    assert a["largest_gap_minutes"]==4
    assert cloud_chart_gaps(pd.DataFrame(),"M1")["known"] is False
    with pytest.raises(ValueError):
        cloud_chart_gaps(f,"BAD")


def test_ui_distinguishes_stage_two_watch_and_ledger_without_adding_trades():
    source=Path("trader/cloud_paper_terminal.py").read_text("utf-8")
    assert "ILE NAPRAWDĘ OTWORZYŁ BOT PAPER" in source
    assert "cloud_paper_visibility(payload,viewport=viewport)" in source
    assert "ETAP 2/3 — WCZESNA OBSERWACJA (SHADOW)" in source
    assert 'st.select_slider(' in source
    assert 'ttl_seconds=35 if choice in ("M1","M2") else 60' in source
    assert "queue_paper(" not in source
    assert "CapitalReadOnly(" not in source
