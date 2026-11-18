"""Regression: tiny candles and oversized US500 Y-axis seen by owner.

UI must scale to real visible OHLC rather than hidden trades' remote SL/TP.
No broker authentication, data synthesis or strategy edits.
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from trader.cloud_chart_visual import candle_price_window, candle_plot_style


def bars():
    idx=pd.date_range("2026-11-18T12:00:00Z",periods=35,freq="min")
    opens=[7364.0 + ((i%9)-4)*.35 for i in range(35)]
    return pd.DataFrame({
        "Open":opens,
        "High":[v+1.3 for v in opens],
        "Low":[v-1.1 for v in opens],
        "Close":[v+.3 for v in opens],
        "Spread":[.4]*35,
    },index=idx)


def test_price_axis_not_flattened_by_remote_history_sl_tp():
    frame=bars()
    view=[frame.index[-31],frame.index[-1]+pd.Timedelta(minutes=1)]
    current=candle_price_window(frame,view)
    assert current is not None
    assert current[0]<frame.Low.iloc[-30:].min()
    assert current[1]>frame.High.iloc[-30:].max()
    assert current[1]-current[0]<10
    # Explicit owner opt-in may include remote stop/target.
    risk=candle_price_window(frame,view,extra_levels=(7320.,7420.))
    assert risk[0]<7320 and risk[1]>7420
    assert risk[1]-risk[0]>current[1]-current[0]  # risk wider


def test_live_quote_far_above_candles_is_not_used_to_autoscale():
    frame=bars()
    view=[frame.index[0],frame.index[-1]]
    original=candle_price_window(frame,view)
    far=candle_price_window(frame,view,mid=7510.)
    assert far==original
    near=candle_price_window(frame,view,mid=7367.)
    assert near is not None
    assert near[1]>=original[1]


def test_viewport_excludes_offscreen_older_wick_outlier():
    frame=bars()
    old_idx=frame.index[0]
    frame.loc[old_idx,"High"]=7460.
    frame.loc[old_idx,"Open"]=7350.
    frame.loc[old_idx,"Close"]=7351.
    # The frame includes an older distant candle, but viewport must ignore it.
    view=[frame.index[-21],frame.index[-1]]
    y=candle_price_window(frame,view)
    assert y[1]<7380


def test_new_chart_style_uses_graphite_theme_no_giant_legend_and_valid_plotly():
    frame=bars()
    view=[frame.index[0],frame.index[-1]]
    y=candle_price_window(frame,view)
    style=candle_plot_style("M1",30,y)
    assert style["plot_bgcolor"]=="#0b1119"
    assert style["showlegend"] is False
    assert style["dragmode"]=="pan"
    assert style["yaxis"]["autorange"] is False
    assert style["yaxis"]["range"]==y
    assert style["hovermode"]=="closest"
    fig=go.Figure(go.Candlestick(
        x=frame.index,open=frame.Open,high=frame.High,
        low=frame.Low,close=frame.Close))
    fig.add_hline(y=7420,line_dash="dash",annotation_text="TP")
    style["xaxis"]["range"]=view
    fig.update_layout(**style)
    assert list(fig.layout.yaxis.range)==y
    assert not fig.layout.showlegend
    assert fig.layout.height>=600


def test_empty_or_invalid_window_is_not_fabricated():
    f=pd.DataFrame()
    assert candle_price_window(f,None) is None
    f=bars()
    assert candle_price_window(f,[f.index[1],f.index[0]]) is None
    empty=pd.DataFrame(columns=["Open","High","Low","Close"],
                       index=pd.DatetimeIndex([],tz="UTC"))
    assert candle_price_window(empty,[f.index[0],f.index[-1]]) is None
    # An incomplete bar might be the only verified candle; no fake history.
    assert candle_price_window(empty,[f.index[0],f.index[-1]],
          moving={"low":7360,"high":7364}) is not None


def test_existing_chart_keeps_REAL_trades_but_stops_price_clipping():
    src=Path("trader/cloud_paper_terminal.py").read_text("utf8")
    assert "candle_price_window(" in src
    assert "candle_plot_style(" in src
    assert "annotate_raw_forward(candles,raw_trial," in src
    assert "annotate_paper_history(candles,chart_paper," in src
    assert 'wide_risk_scale=st.checkbox(' in src
    assert 'price_range=candle_price_window(' in src
    assert 'candles.update_layout(**layout)' in src
    assert "modeBarButtonsToRemove" in src
    assert "chart_mode==\"BIEŻĄCE ŚWIECE\"" in src
    assert 'mode="lines+markers" if len(points)>1' not in src
    assert "queue_paper(" not in src
