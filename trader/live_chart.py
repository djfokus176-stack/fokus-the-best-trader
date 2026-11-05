"""Non-tradable sampled-quote preview for a moving Streamlit candle chart.

Never mix these REST snapshots with the closed OHLC bars that the trading
strategies, checkpoint worker or PAPER execution use.
"""
from __future__ import annotations
from datetime import datetime
import pandas as pd
from .market import PERIOD, MarketQuote


def quote_sample(history, quote: MarketQuote, timeframe: str, *, limit=360):
    """Append validated vendor-timestamped MID; deduplicate repeated vendor quotes."""
    if timeframe not in PERIOD:
        return []
    period=PERIOD[timeframe]
    rows=[r for r in list(history or []) if
          r.get("epic")==quote.epic and r.get("environment")==quote.environment
          and r.get("timeframe")==timeframe]
    if not quote.fresh or quote.update_utc is None:
        return rows[-limit:]
    tick=pd.Timestamp(quote.update_utc)
    close=tick.floor(f"{period}s")+pd.Timedelta(seconds=period)
    if rows and pd.Timestamp(rows[-1]["time"])>=tick:
        return rows[-limit:]
    item={"epic":quote.epic,"environment":quote.environment,"timeframe":timeframe,
          "time":tick.isoformat(),"bar_close":close.isoformat(),
          "mid":float(quote.mid),"bid":float(quote.bid),"ask":float(quote.ask)}
    # Old minute samples are not needed for forming-bar preview.
    rows=[r for r in rows if r.get("bar_close")==item["bar_close"]]
    return (rows+[item])[-max(2,int(limit)):]


def sampled_preview(samples, *, closed_time: datetime | None = None):
    """A small sampled sub-minute OHLC, NOT a real tick-built broker candle."""
    if not samples:
        return None
    rows=list(samples)
    close=pd.Timestamp(rows[-1]["bar_close"])
    if closed_time is not None and close<=pd.Timestamp(closed_time):
        return None
    rows=[r for r in rows if r["bar_close"]==rows[-1]["bar_close"]]
    mids=[float(x["mid"]) for x in rows]
    return {"time":close,
            "Open":mids[0],"High":max(mids),"Low":min(mids),
            "Close":mids[-1],"samples":len(rows),
            "last_tick":pd.Timestamp(rows[-1]["time"])}


def show_quote_preview(fig, preview, *, bars, visible_bars=30, auto_zoom=True):
    """Plot incomplete quote-sample candle separately from confirmed OHLC.

    The label is mandatory: it is NOT a finished M1 candle and may miss
    intrabar extremes between REST polls.
    """
    import plotly.graph_objects as go
    if preview is not None:
        rising=preview["Close"]>=preview["Open"]
        color="#26da93" if rising else "#ff4561"
        provider_ohlc=preview.get("source")=="Capital.com /prices • bieżąca OHLC"
        fig.add_trace(go.Candlestick(
            x=[preview["time"]],open=[preview["Open"]],
            high=[preview["High"]],low=[preview["Low"]],close=[preview["Close"]],
            increasing={"line":{"color":"#26da93","width":3},
                        "fillcolor":"rgba(38,218,147,0.55)"},
            decreasing={"line":{"color":"#ff4561","width":3},
                        "fillcolor":"rgba(255,69,97,0.55)"},
            name=("LIVE /prices • świeca w trakcie (NIE PAPER)" if provider_ohlc
                  else "LIVE MID • niepełna świeca z próbek REST"),
            hovertemplate=None,showlegend=True))
        fig.add_trace(go.Scatter(
            x=[preview["time"]],y=[preview["Close"]],
            mode="markers+text",text=["◀ LIVE (próbki)"],
            textposition="middle right",textfont={"color":color,"size":12},
            marker={"symbol":"circle","size":9,"color":color},
            name=("Bieżący MID /prices" if provider_ohlc else
                  "Bieżący MID (próbki co kilka sekund)"),
            hovertemplate="Wstępny MID %{y:.2f}<br>Data próbki %{x}<extra></extra>"))
    if bars is not None and not bars.empty:
        n=max(15,min(int(visible_bars),len(bars)))
        tail=bars.tail(n)
        close=preview["time"] if preview else bars.index[-1]
        period=(bars.index[-1]-bars.index[-2]) if len(bars)>=2 else pd.Timedelta(minutes=1)
        fig.update_xaxes(range=[tail.index[0]-period/2, close+period*2.2])
        if auto_zoom:
            lows=pd.to_numeric(tail["Low"],errors="coerce").dropna()
            highs=pd.to_numeric(tail["High"],errors="coerce").dropna()
            if not lows.empty and not highs.empty:
                lo=float(lows.min());hi=float(highs.max())
                if preview is not None:
                    lo=min(lo,preview["Low"]);hi=max(hi,preview["High"])
                padding=max(0.8,(hi-lo)*0.10)
                fig.update_yaxes(range=[lo-padding,hi+padding],fixedrange=False)
    return fig
