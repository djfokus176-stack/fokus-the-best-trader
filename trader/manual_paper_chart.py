"""Manual PAPER marker overlay. Never constructs signals or transactions."""
from __future__ import annotations

from .paper_trade_trails import _utc, _num


def annotate_manual_test(fig, report, *, viewport=None):
    import plotly.graph_objects as go
    if (not isinstance(report,dict)
            or report.get("status")!="OWNER_MANUAL_PAPER_ONLY"):
        return fig
    lower=_utc(viewport[0]) if isinstance(viewport,(list,tuple)) and len(viewport)==2 else None
    upper=_utc(viewport[1]) if isinstance(viewport,(list,tuple)) and len(viewport)==2 else None
    rows=list(report.get("recent") or [])
    active=report.get("active")
    if isinstance(active,dict):
        rows.append(active)
    for p in rows[-12:]:
        if not isinstance(p,dict) or p.get("side") not in ("LONG","SHORT"):
            continue
        side=p["side"]
        entry=_num(p.get("entry_mid"))
        when=_utc(p.get("entry_bar_open_utc"))
        if (entry is not None and when is not None and
                (lower is None or when>=lower) and (upper is None or when<=upper)):
            c="#33d9a5" if side=="LONG" else "#ff6179"
            fig.add_trace(go.Scatter(
                x=[when],y=[entry],mode="markers+text",
                text=["RĘCZNY "+side],textposition="top center",
                name="🧪 TEST RĘCZNY "+side,showlegend=False,
                textfont={"size":12,"color":c},
                marker={"symbol":"star","size":17,"color":c,
                        "line":{"color":"#172536","width":2}},
                hovertemplate=(
                    f"RĘCZNY PAPER {side} — tylko symulacja<br>"
                    f"OPEN {when.tz_convert('Europe/Warsaw').strftime('%d.%m.%Y %H:%M:%S')}"
                    f"<br>Cena MID {entry:.2f} pkt"
                    f"<br>SL {float(p.get('stop') or 0):.2f}"
                    f"<br>TP {float(p.get('target') or 0):.2f}"
                    "<br>Potwierdzono na zamkniętej następnej M1"
                    "<extra></extra>"),
            ))
        closed=p.get("status") in ("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT")
        exit_time=_utc(p.get("closed_utc"))
        exit_price=_num(p.get("exit_mid"))
        pnl=_num(p.get("pnl_pts"))
        if (closed and exit_time is not None and exit_price is not None
                and pnl is not None and (lower is None or exit_time>=lower)
                and (upper is None or exit_time<=upper)):
            positive=pnl>0
            c="#34d399" if positive else "#f87171"
            fig.add_trace(go.Scatter(
                x=[exit_time],y=[exit_price],mode="markers+text",
                text=[f"TEST CLOSE {pnl:+.2f} pkt"],
                textposition="bottom center",name="🧪 MANUAL CLOSE",
                showlegend=False,textfont={"size":12,"color":c},
                marker={"symbol":"diamond","size":16,"color":c,
                        "line":{"color":"#172536","width":2}},
                hovertemplate=(
                    f"RĘCZNY PAPER {side} {p['status']}"
                    f"<br>CLOSE {exit_time.tz_convert('Europe/Warsaw').strftime('%d.%m.%Y %H:%M:%S')}"
                    f"<br>Wyjście MID {exit_price:.2f} pkt"
                    f"<br>WYNIK NETTO {pnl:+.2f} pkt"
                    "<br>Wynik modelowy, nie zlecenie brokera."
                    "<extra></extra>"),
            ))
    return fig
