"""Clearly distinguish a real OPEN paper position from historical setups."""
from __future__ import annotations

def annotate_open_paper(fig, position):
    """OPEN only: draw separate MID reference and modeled executable fill."""
    if not position or position.get("status")!="OPEN":
        return fig
    for label,value,color in (
        ("PAPER ENTRY MID (OHLC)",position.get("entry_mid"),"#77c8ff"),
        ("PAPER FILL BID/ASK (MODEL)",position.get("entry_executable"),"#f6b157"),
        ("PAPER SL",position.get("stop_mid"),"#ff6680"),
        ("PAPER TP",position.get("target_mid"),"#3bdf99"),
    ):
        if value is not None:
            fig.add_hline(y=float(value),line={"color":color,"width":2,"dash":"dash"},
                annotation_text=f"{label} · {str(position.get('trade_id',''))[:8]}",
                annotation_font_color=color)
    return fig



def annotate_paper_history(fig, positions, epic, source, timeframe, max_rows=80):
    """Plot strictly ledger-backed PAPER OPEN/CLOSED events, NEVER old setups.

    An entry is reconstructed from the next CLOSED bar. The arrow therefore
    means the PAPER engine recorded OPEN, not an actual broker order.
    """
    import pandas as pd
    import plotly.graph_objects as go
    symbols={"LONG":("triangle-up","#3de59a","OTWARCIE LONG"),
             "SHORT":("triangle-down","#ff425d","OTWARCIE SHORT")}
    for pos in list(positions or [])[:max_rows]:
        if any(pos.get(k)!=v for k,v in (
            ("epic",epic),("source",source),("timeframe",timeframe))):
            continue
        side=pos.get("side")
        if side not in symbols:
            continue
        symbol,color,caption=symbols[side]
        trade_id=str(pos.get("trade_id",""))[:9]
        if pos.get("opened_utc") and pos.get("entry_mid") is not None:
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(pos["opened_utc"])],
                y=[float(pos["entry_mid"])],
                mode="markers+text",text=[caption],
                textposition="bottom center" if side=="LONG" else "top center",
                textfont={"color":color,"size":12},
                marker={"symbol":symbol,"size":18,"color":color,
                        "line":{"width":1.5,"color":"#ffffff"}},
                name=f"{caption} • PAPER {trade_id}",
                hovertemplate=(f"{caption} • PAPER {trade_id}<br>Wejście odtworzone "
                               "z zamkniętej świecy (nie broker)<br>%{x}<br>"
                               "MID %{y:.2f}<extra></extra>")))
        if pos.get("closed_utc") and pos.get("exit_mid") is not None:
            outcome=str(pos.get("status","CLOSED"))
            if outcome not in ("CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT"):
                continue
            pnl=pos.get("pnl_pts")
            result=f"{float(pnl):+.2f} pkt" if pnl is not None else "brak P&L"
            label=f"ZAMKNIJ {result}"
            text_color=("#ff6575" if pnl is not None and float(pnl)<0
                        else "#3de59a")
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(pos["closed_utc"])],
                y=[float(pos["exit_mid"])],
                mode="markers+text",text=[label],
                textfont={"color":text_color,"size":12},
                textposition="top center",
                marker={"symbol":"square","size":16,"color":"#3de59a",
                        "line":{"width":2,"color":"#ffffff"}},
                name=f"ZAMKNIJ • PAPER {trade_id}",
                hovertemplate=(f"ZAMKNIJ • {outcome} • {trade_id}<br>"
                               f"P&L {result}<br>%{{x}}<br>"
                               "Wyjście MID %{y:.2f}<extra></extra>")))
    return fig
