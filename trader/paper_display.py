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
