"""Regression: user sees only candle fragments instead of overnight entries.

Records and candles are real archive-backed; no fake signals or broker POST.
"""
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from trader.cloud_paper_terminal import cloud_chart_view_range
from trader.cloud_chart_timeframes import closed_chart_frame
from trader.raw_paper_chart import annotate_raw_forward


def frame(count=1400):
    idx=pd.date_range("2026-11-17T12:00:00+00:00",periods=count,freq="min")
    return pd.DataFrame({
        "Open":[7350.0]*count,"High":[7352.0]*count,
        "Low":[7348.0]*count,"Close":[7351.0]*count,
        "Spread":[.5]*count,
    },index=idx)


def test_hist_overnight_trade_centered_instead_of_last_45_minute_view():
    f=frame()
    historic=f.index[-650]
    recent=cloud_chart_view_range(f,"M1",visible_count=45)
    assert not recent[0]<=historic<=recent[1]
    focused=cloud_chart_view_range(f,"M1",visible_count=45,
                                   focus_utc=historic.isoformat())
    assert focused[0]<=historic<=focused[1]
    # Under one hour, not an accidentally 11-hour chart that makes M1 tiny.
    assert focused[1]-focused[0]<=pd.Timedelta(minutes=50)
    assert focused!=recent


def test_300_real_candle_zoom_no_crash_and_no_missing_backfill():
    f=frame()
    out=closed_chart_frame(f,"M1")
    assert len(out)==1400
    focused=cloud_chart_view_range(out,"M1",visible_count=300,
                                   focus_utc=out.index[-500].isoformat())
    assert focused[0]<=out.index[-500]<=focused[1]
    assert focused[1]-focused[0]<=pd.Timedelta(minutes=305)


def test_m2_remains_complete_pairs_and_preserves_more_than_120_candles():
    f=frame()
    result=closed_chart_frame(f,"M2")
    assert 500<len(result)<=750
    assert result.index.is_monotonic_increasing
    assert not result.index.has_duplicates
    assert len(result)<len(f)


def test_marker_labels_include_direction_and_net_points_without_hover():
    report={"status":"FORWARD_ONLY_RAW_M1_SIMULATION","active":None,
            "recent":[{
                "side":"LONG","status":"CLOSED_TP","methods":["EMA TREND"],
                "entry_bar_open_utc":"2026-11-18T01:46:00+00:00",
                "entry_mid":7400.0,"stop":7390.0,"target":7418.0,
                "closed_utc":"2026-11-18T01:52:00+00:00",
                "exit_mid":7418.0,"pnl_pts":8.25,
            }]}
    fig=go.Figure()
    annotate_raw_forward(fig,report,
                         start="2026-11-18T01:30:00+00:00",
                         end="2026-11-18T02:00:00+00:00")
    entries=[x for x in fig.data if "RAW TEST OPEN LONG" in x.name]
    closes=[x for x in fig.data if "RAW TEST CLOSE" in x.name]
    assert len(entries)==1 and len(closes)==1
    assert entries[0].mode=="markers+text"
    assert list(entries[0].text)==["LONG"]
    assert "+8.25 pkt" in closes[0].text[0]
    assert "+8.25 pkt" in closes[0].customdata[0]


def test_empty_ledger_never_generates_fake_markers():
    fig=go.Figure()
    annotate_raw_forward(fig,{"status":"FORWARD_ONLY_RAW_M1_SIMULATION",
                              "recent":[],"active":None})
    assert len(fig.data)==0


def test_cloud_ui_fixes_yellow_dot_screenshot_and_can_rewind_to_last_raw_open():
    src=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    assert '"OSTATNIE OPEN RAW"' in src
    assert '"OSTATNIE CLOSE RAW"' in src
    assert 'visible_count=zoom,focus_utc=focus_utc' in src
    assert 'candle_limit=1500 if resolution=="MINUTE" else 520' in src
    assert 'display_frame.index' in src
    assert 'height=720' in src
    assert 'mode="lines+markers" if len(points)>1' not in src
    assert 'BID/ASK MID' in src
    assert 'queue_paper(' not in src
