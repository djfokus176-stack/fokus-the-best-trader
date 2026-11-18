"""Display-only price scale for a readable US500 candle chart.

Keep the zoom tied to REAL *visible* OHLC, never inactive/past trade SL/TP
or distant off-window markers. This helper is read-only and cannot create
signals, data, orders, or artificial candles.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd


def _number(value):
    try:
        result=float(value)
    except (ValueError,TypeError,OverflowError):
        return None
    return result if isfinite(result) else None


def candle_price_window(frame, viewport, *, moving=None, mid=None,
                        extra_levels=(), minimum_span=4.0):
    """Return a non-flat y-range from REAL visible candle highs/lows.

    Plotly's default autorange includes *all* traces and horizontal levels:
    distant SL/TP or offscreen trade markers can flatten the visible candles.
    Here candle geometry always drives the default scale; explicit risk-level
    mode may widen it intentionally by passing extra_levels.
    """
    if not isinstance(frame,pd.DataFrame) or viewport is None:
        return None
    if len(viewport)!=2 or not isinstance(frame.index,pd.DatetimeIndex):
        return None
    try:
        begin,end=(pd.Timestamp(v) for v in viewport)
    except (TypeError,ValueError,OverflowError):
        return None
    if (begin.tzinfo is None or end.tzinfo is None or
            begin>=end or frame.index.tz is None):
        return None
    recent=frame.loc[(frame.index>=begin)&(frame.index<=end)]
    lows=[]
    highs=[]
    if not recent.empty and {"Low","High"}.issubset(recent.columns):
        for low,high in zip(recent["Low"],recent["High"]):
            a,b=_number(low),_number(high)
            if a is not None and b is not None and a>0 and b>=a:
                lows.append(a)
                highs.append(b)
    if not lows:
        if not isinstance(moving,dict):
            return None
        a,b=_number(moving.get("low")),_number(moving.get("high"))
        if a is None or b is None or a<=0 or b<a:
            return None
        lows=[a]
        highs=[b]
    low,high=min(lows),max(highs)
    # MID is included only if it is a small, nearby *current* quote. A stale,
    # distant or historical quote must not shrink all candle bodies.
    quote=_number(mid)
    base=max(high-low,minimum_span)
    if quote is not None and low-base*.35<=quote<=high+base*.35:
        low=min(low,quote)
        high=max(high,quote)
    if isinstance(moving,dict):
        a,b=_number(moving.get("low")),_number(moving.get("high"))
        if a is not None and b is not None and a>0 and b>=a:
            if low-base*.45<=a<=high+base*.45 and low-base*.45<=b<=high+base*.45:
                low=min(low,a)
                high=max(high,b)
    # Only an explicit opt-in 'risk' chart includes stop/target. Never alter
    # candle data, or infer missing prices to fill history.
    for level in extra_levels:
        v=_number(level)
        if v is not None and v>0:
            low=min(low,v)
            high=max(high,v)
    spread=max(high-low,minimum_span)
    middle=(low+high)/2
    pad=max(.55,spread*.10)
    low=min(low-pad,middle-(minimum_span/2+pad))
    high=max(high+pad,middle+(minimum_span/2+pad))
    return [round(low,4),round(high,4)]


def candle_plot_style(choice,zoom,price_range,*,mode="BIEŻĄCE ŚWIECE"):
    """Minimal black/graphite NGT-like chart, preserving real Plotly controls."""
    return {
        "height":690,
        "xaxis_rangeslider_visible":False,
        "template":"plotly_dark",
        "uirevision":"fokus_chart_v5_"+str(choice)+"_"+str(mode)+"_"+str(zoom),
        "paper_bgcolor":"#0b1119",
        "plot_bgcolor":"#0b1119",
        "font":{"size":12,"color":"#dce5ed","family":"Arial, sans-serif"},
        "showlegend":False,
        "dragmode":"pan",
        "hovermode":"closest",
        "hoverlabel":{"bgcolor":"#131d29","bordercolor":"#26374b",
                      "font":{"size":12,"color":"#eaf1f6"}},
        "xaxis":{
            "showgrid":True,"gridcolor":"#1f2937","gridwidth":.7,
            "showline":False,"zeroline":False,
            "showspikes":True,"spikecolor":"#71839b",
            "spikemode":"across","spikesnap":"cursor",
            "spikethickness":1,
            "tickformat":"%H:%M","hoverformat":"%d.%m.%Y %H:%M",
            "nticks":9,
            "fixedrange":False,
        },
        "yaxis":{
            "showgrid":True,"gridcolor":"#202b38","gridwidth":.7,
            "showline":False,"zeroline":False,
            "tickformat":".2f","nticks":9,"side":"right",
            "fixedrange":False,
            "autorange":False if price_range else True,
            **({"range":price_range} if price_range else {}),
        },
        "margin":{"l":8,"r":64,"t":24,"b":36},
    }
