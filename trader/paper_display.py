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
    """Compact ledger-backed PAPER events: max five grouped legend entries.

    Plot *only* actual v3 OPEN and completed CLOSED positions in the
    requested instrument/source/timeframe. Never infer an entry from an
    earlier strategy signal. Each marker retains its own exact trade ID,
    strategy and modeled P&L in hover, without adding legend entries
    for every historical trade. Chart-only presentation change.
    """
    from html import escape
    from math import isfinite
    import pandas as pd
    import plotly.graph_objects as go

    groups = {
        "OPEN_LONG": {"name":"PAPER: otwarcie LONG",
                      "symbol":"triangle-up","color":"#3de59a"},
        "OPEN_SHORT":{"name":"PAPER: otwarcie SHORT",
                      "symbol":"triangle-down","color":"#ff425d"},
        "CLOSED_GAIN":{"name":"PAPER: zamknięcie +",
                       "symbol":"square","color":"#3de59a"},
        "CLOSED_LOSS":{"name":"PAPER: zamknięcie −",
                       "symbol":"square","color":"#ff6575"},
        "CLOSED_FLAT":{"name":"PAPER: zamknięcie 0 / brak wyniku",
                       "symbol":"square","color":"#a8b3c6"},
    }
    events={key:{"x":[],"y":[],"text":[]} for key in groups}
    for pos in list(positions or [])[:max_rows]:
        if any(pos.get(k)!=v for k,v in
               (("epic",epic),("source",source),("timeframe",timeframe))):
            continue
        side=pos.get("side")
        if side not in ("LONG","SHORT"):
            continue
        trade_id=escape(str(pos.get("trade_id","BRAK ID")))
        strategy=escape(str(pos.get("strategy","NIEZNANA")))
        if pos.get("opened_utc") and pos.get("entry_mid") is not None:
            try:
                when=pd.Timestamp(pos["opened_utc"])
                price=float(pos["entry_mid"])
            except (TypeError,ValueError,OverflowError):
                when=None
            if when is not None and isfinite(price):
                group=events["OPEN_"+side]
                group["x"].append(when)
                group["y"].append(price)
                group["text"].append(
                    f"OTWARCIE PAPER {side}<br>Strategia: {strategy}"
                    f"<br>ID: {trade_id}<br>Świeca UTC: {when}"
                    f"<br>Wejście MID: {price:.2f}<br>"
                    "Odtworzone z zamkniętej świecy, nie zlecenie brokera")
        status=str(pos.get("status",""))
        if (status not in ("CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT")
                or not pos.get("closed_utc") or pos.get("exit_mid") is None):
            continue
        try:
            when=pd.Timestamp(pos["closed_utc"])
            price=float(pos["exit_mid"])
            pnl=(float(pos["pnl_pts"]) if pos.get("pnl_pts") is not None
                 else None)
        except (TypeError,ValueError,OverflowError):
            continue
        if not isfinite(price) or (pnl is not None and not isfinite(pnl)):
            continue
        key=("CLOSED_GAIN" if pnl is not None and pnl>0 else
             "CLOSED_LOSS" if pnl is not None and pnl<0 else "CLOSED_FLAT")
        group=events[key]
        group["x"].append(when)
        group["y"].append(price)
        result=(f"{pnl:+.2f} pkt" if pnl is not None else "BRAK P&L")
        group["text"].append(
            f"ZAMKNIĘCIE PAPER {side}<br>Strategia: {strategy}"
            f"<br>ID: {trade_id}<br>Status: {escape(status)}"
            f"<br>Wynik po kosztach: {result}<br>"
            f"Świeca UTC: {when}<br>Wyjście MID: {price:.2f}")
    for name,style in groups.items():
        e=events[name]
        if not e["x"]:
            continue
        fig.add_trace(go.Scatter(
            x=e["x"],y=e["y"],text=e["text"],mode="markers",
            name=style["name"],showlegend=True,
            marker={"symbol":style["symbol"],"size":14,
                    "color":style["color"],
                    "line":{"width":1.5,"color":"#ffffff"}},
            hovertemplate="%{text}<extra></extra>",
        ))
    return fig
