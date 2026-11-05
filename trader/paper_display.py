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
    """Add actual archived PAPER lifecycle events, not historical setup guesses.

    entry_mid and exit_mid are reconstructed from CLOSED candles, never
    broker fills. OPEN cannot be labeled at the moment of the real bar open.
    """
    import pandas as pd
    import plotly.graph_objects as go
    key={"LONG":("triangle-up","#47dcb0"),
         "SHORT":("triangle-down","#ff6e82")}
    for pos in list(positions or [])[:max_rows]:
        if any(pos.get(k)!=v for k,v in
               (("epic",epic),("source",source),("timeframe",timeframe))):
            continue
        side=pos.get("side")
        if side not in key:
            continue
        symbol,color=key[side]
        trade_id=str(pos.get("trade_id",""))[:9]
        if pos.get("setup_utc"):
            fig.add_vline(x=pd.Timestamp(pos["setup_utc"]).timestamp()*1000,
                line_color=color,line_dash="dot",opacity=.18)
        if pos.get("opened_utc") and pos.get("entry_mid") is not None:
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(pos["opened_utc"])],
                y=[float(pos["entry_mid"])],
                mode="markers+text",text=[f"PAPER {side}"],
                textposition="top center",
                marker={"symbol":symbol,"size":14,"color":color},
                name=f"PAPER {side} • {trade_id}",
                hovertemplate=(f"PAPER {side} • {trade_id}<br>Otworzenie odtworzone "
                               "po ZAMKNIĘCIU świecy<br>%{x}<br>"
                               "MID %{y:.2f}<extra></extra>")))
        if pos.get("closed_utc") and pos.get("exit_mid") is not None:
            pnl=pos.get("pnl_pts")
            outcome=str(pos.get("status","CLOSED"))
            label=f"{outcome} {float(pnl):+.2f} pkt" if pnl is not None else outcome
            icon="#ff677d" if pnl is not None and float(pnl)<0 else "#f8c954"
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(pos["closed_utc"])],
                y=[float(pos["exit_mid"])],mode="markers+text",
                text=[label],textposition="top center",
                marker={"symbol":"x" if outcome=="CLOSED_SL" else "diamond",
                        "size":13,"color":icon},
                name=f"Zamknięcie PAPER • {trade_id}",
                hovertemplate=(f"{label}<br>{trade_id}<br>%{{x}}<br>"
                               "Wyjście MID %{y:.2f}<extra></extra>")))
    return fig
