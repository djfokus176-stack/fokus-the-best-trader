"""Regression: owner can see real modeled CLOSE events beyond 1500 live M1 bars.

No broker calls, no invented fills, no Supabase mutation. All OHLC synthetic.
"""
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go

from trader.cloud_paper_terminal import cloud_paper_positions, cloud_chart_view_range
from trader.cloud_paper_visibility import cloud_paper_visibility
from trader.paper_display import annotate_paper_history


def _minute_history():
    ix=pd.date_range("2026-11-23T00:00:00Z",periods=3600,freq="min")
    return pd.DataFrame({
        "Open":7200.0,"High":7201.0,"Low":7199.0,
        "Close":7200.0,"Spread":0.4
    },index=ix)


def _closed_trade(frame):
    close=frame.index[-2000]
    opened=close-pd.Timedelta(minutes=19)
    pos={
        "trade_id":"genuine-test-20261124-close",
        "source":"Capital.com DEMO REST","epic":"US500",
        "timeframe":"MINUTE","side":"LONG",
        "created_utc":opened.isoformat(),
        "opened_utc":opened.isoformat(),
        "closed_utc":close.isoformat(),
        "entry_mid":7200.0,"exit_mid":7188.0,
        "pnl_pts":-13.10,"status":"CLOSED_TIMEOUT",
        "strategy":"EMA PULLBACK",
    }
    payload={"tables":{"paper_positions_v3":[pos]},
             "meta":{"epic":"US500","source":"Capital.com DEMO REST"}}
    return payload,pos


def test_recent_live_candles_cannot_show_yesterday_close_but_history_can():
    frame=_minute_history()
    payload,pos=_closed_trade(frame)
    live=frame.iloc[-1500:]
    live_recent,live_markers=cloud_paper_positions(payload,live)
    assert len(live_recent)==1
    assert live_markers==[]  # Explain absence instead of forging a marker.
    extended_recent,markers=cloud_paper_positions(payload,frame)
    assert len(extended_recent)==1
    assert len(markers)==1
    viewport=cloud_chart_view_range(frame,"M1",visible_count=45,
                                    focus_utc=pos["closed_utc"])
    close=pd.Timestamp(pos["closed_utc"])
    assert viewport[0]<=close<=viewport[1]
    fig=annotate_paper_history(go.Figure(),markers,
        "US500","Capital.com DEMO REST",None,show_labels=True)
    closes=[t for t in fig.data if "zamknięcie" in t.name]
    opens=[t for t in fig.data if "otwarcie" in t.name]
    assert len(opens)==len(closes)==1
    assert closes[0].mode=="markers+text"
    assert closes[0].text[0]=="-13.10 pkt"
    assert "CLOSED_TIMEOUT" in closes[0].customdata[0]
    assert "genuine-test-20261124-close" in closes[0].customdata[0]
    assert closes[0].x[0]==close
    assert opens[0].text[0]=="LONG"
    counts=cloud_paper_visibility(payload,viewport=viewport)
    assert counts["visible_closed"]==1
    assert counts["visible_open"]==1


def test_default_marker_api_remains_compact_hover_only():
    frame=_minute_history()
    payload,_=_closed_trade(frame)
    rows,_=cloud_paper_positions(payload,frame)
    fig=annotate_paper_history(go.Figure(),rows,
        "US500","Capital.com DEMO REST",None)
    assert all(t.mode=="markers" for t in fig.data)
    assert all(t.hovertemplate=="%{text}<extra></extra>" for t in fig.data)


def test_ui_historical_fetch_is_opt_in_and_does_not_change_live_renderer():
    src=Path("trader/cloud_paper_terminal.py").read_text(encoding="utf-8")
    assert 'history_mode=(chart_mode!="BIEŻĄCE ŚWIECE")' in src
    assert 'candle_limit=1500 if resolution=="MINUTE" else 520' in src
    assert 'if history_mode and resolution=="MINUTE":' in src
    assert 'candle_limit=5000' in src
    assert 'cache.get("history_mode")!=history_mode' in src
    assert '"OSTATNIE CLOSE PAPER v3"' in src
    assert 'show_labels=True' in src
    assert "queue_paper(" not in src
