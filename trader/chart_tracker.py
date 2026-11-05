"""Last-scanned candle highlight for the real M1/M5/M15/H1 Plotly chart.

The marker advances ONLY when a new confirmed closed candle arrives.
It does not simulate live tick motion or broker orders.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
from .market import PERIOD

COLORS={"WAIT":"#e3bf4a","LONG":"#41de97","SHORT":"#ff667e"}


def annotate_scan(fig,frame,decision,record=None,bar_limit=120,resolution="MINUTE",source="Capital.com DEMO REST"):
    if frame is None or frame.empty:
        return fig
    side=str(getattr(decision,"action","WAIT")).upper()
    if side not in COLORS:side="WAIT"
    mark=frame.iloc[-1]
    tick=frame.index[-1]
    color=COLORS[side]
    count=int(record.get("scan_no",0)) if record else 0
    was_new=bool(record.get("new_candle",False)) if record else False
    csv_replay="CSV" in str(source).upper()
    marker_label="🤖 REPLAY" if csv_replay else "🤖 BOT"
    caption=(f"{'HISTORYCZNY REPLAY CSV' if csv_replay else 'BOT ODCZYT'} "
             f"#{count} • {side} • {'NOWA ŚWIECA' if was_new else 'OSTATNIA ŚWIECA'}")
    fig.add_trace(go.Scatter(
        x=[tick],y=[float(mark.Close)],mode="markers+text",
        marker={"symbol":"circle","size":17,"color":color,
                "line":{"width":2,"color":"#f4f7fc"}},
        text=[marker_label],textposition="top center",textfont={"color":color,"size":12},
        name="🤖 Ostatnia zamknięta świeca (CSV REPLAY)" if csv_replay
             else "🤖 Ostatnia sprawdzona zamknięta świeca",
        hovertemplate=caption+"<br>%{x}<br>MID %{y:.2f}<extra></extra>"
    ))
    fig.add_shape(type="line",xref="x",yref="paper",x0=tick,x1=tick,
                  y0=0,y1=1,line={"color":color,"dash":"dot","width":1})
    fig.add_hline(y=float(mark.Close),line={"color":color,"dash":"dot","width":1},
                  opacity=.40)
    n=max(40,int(bar_limit))
    if len(frame)>n:
        future=pd.Timedelta(seconds=2*PERIOD.get(resolution,60))
        fig.update_xaxes(range=[frame.index[-n],tick+future])
    return fig
