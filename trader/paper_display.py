"""Clearly distinguish a real OPEN paper position from historical setups."""
from __future__ import annotations

from .paper_method_labels import method_attribution
from .trade_time_labels import in_poland, open_time_details

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
        "OPEN_LONG": {"name":"OTWARCIE LONG · symulacja",
                      "symbol":"triangle-up","color":"#3de59a"},
        "OPEN_SHORT":{"name":"OTWARCIE SHORT · symulacja",
                      "symbol":"triangle-down","color":"#ff425d"},
        "CLOSED_GAIN":{"name":"ZAMKNIĘCIE + · symulacja",
                       "symbol":"square","color":"#3de59a"},
        "CLOSED_LOSS":{"name":"ZAMKNIĘCIE − · symulacja",
                       "symbol":"square","color":"#ff6575"},
        "CLOSED_FLAT":{"name":"ZAMKNIĘCIE 0 · symulacja",
                       "symbol":"square","color":"#a8b3c6"},
    }
    events={key:{"x":[],"y":[],"text":[]} for key in groups}
    for pos in list(positions or [])[:max_rows]:
        # timeframe=None is used ONLY by the read-only CLOUD M15 overview:
        # it marks actual M1/M5/M15/H1 PAPER positions on a M15 time axis.
        # All existing per-TF charts still restrict their markers exactly.
        if (pos.get("epic")!=epic or pos.get("source")!=source or
                (timeframe is not None and pos.get("timeframe")!=timeframe)):
            continue
        side=pos.get("side")
        if side not in ("LONG","SHORT"):
            continue
        trade_id=escape(str(pos.get("trade_id","BRAK ID")))
        attribution=method_attribution(pos)
        strategy=escape(attribution["label"])
        pos_tf=escape(str(pos.get("timeframe","BRAK")))
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
                times=open_time_details(pos)
                group["text"].append(
                    f"OTWARCIE {side} — SYMULACJA"
                    f"<br>Strategia: {strategy}"
                    f"<br>Interwał pozycji: {pos_tf}"
                    f"<br>Godzina modelowanego wejścia (Polska): {times['model_pl']}"
                    f"<br>Godzina potwierdzenia M1 (Polska): {times['confirmed_pl']}"
                    f"<br>Godzina zapisu przez worker (Polska): {times['detected_pl']}"
                    f"<br>Świeca UTC: {when}"
                    f"<br>Wejście MID: {price:.2f} pkt"
                    f"<br>ID: {trade_id}"
                    "<br>Wirtualne wejście z OHLC; nie zlecenie brokera.")
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
            f"ZAMKNIĘCIE {side} — SYMULACJA"
            f"<br>Strategia: {strategy}"
            f"<br>Interwał pozycji: {pos_tf}"
            f"<br>Godzina zamknięcia (Polska): {in_poland(pos.get('closed_utc'))}"
            f"<br>ID: {trade_id}<br>Status: {escape(status)}"
            f"<br>Wynik netto po kosztach: {result}"
            f"<br>Świeca UTC: {when}<br>Wyjście MID: {price:.2f} pkt"
            "<br>Rozliczenie modelowe; nie broker.")
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
