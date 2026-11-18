"""Markers & level lines for REAL forward-recorded RAW M1 PAPER positions.

Overlay only. Plotly candle series must come from archived Capital DEMO OHLC;
we never manufacture a candle, signal, execution or realized P&L.
"""
from __future__ import annotations

from html import escape
from math import isfinite
import pandas as pd


def _stamp(value):
    if not value:
        return None
    try:
        parsed=pd.Timestamp(value)
        return parsed.tz_convert("UTC") if parsed.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None


def _num(value):
    try:
        result=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return result if isfinite(result) else None


def annotate_raw_forward(fig, report, *, start=None, end=None):
    """Put actual synthetic OPEN/CLOSED markers on the existing candle plot."""
    import plotly.graph_objects as go

    if (not isinstance(report,dict) or
            report.get("status")!="FORWARD_ONLY_RAW_M1_SIMULATION"):
        return fig
    lower,upper=_stamp(start),_stamp(end)
    positions=list(report.get("recent") or [])
    active=report.get("active")
    if isinstance(active,dict) and active.get("status")=="OPEN":
        positions.append(active)
    groups={
        "LONG":dict(name="🟢 RAW TEST OPEN LONG",
                    symbol="triangle-up",color="#35ffb0"),
        "SHORT":dict(name="🔴 RAW TEST OPEN SHORT",
                    symbol="triangle-down",color="#ff6680"),
        "GAIN":dict(name="✅ RAW TEST CLOSE + pkt",
                    symbol="diamond",color="#49f6b9"),
        "LOSS":dict(name="❌ RAW TEST CLOSE − pkt",
                    symbol="diamond",color="#ff7a7a"),
    }
    entries={k:{"x":[],"y":[],"text":[],"labels":[]} for k in groups}
    for pos in positions[-90:]:
        if not isinstance(pos,dict) or pos.get("side") not in ("LONG","SHORT"):
            continue
        side=pos["side"]
        methods=escape(", ".join(str(x) for x in (pos.get("methods") or [])[:6]))
        stop,target=_num(pos.get("stop")),_num(pos.get("target"))
        when=_stamp(pos.get("entry_bar_open_utc"))
        entry=_num(pos.get("entry_mid"))
        if when is not None and entry is not None and (
                (lower is None or when>=lower) and (upper is None or when<=upper)):
            item=entries[side]
            item["x"].append(when)
            item["y"].append(entry)
            item["labels"].append("LONG" if side=="LONG" else "SHORT")
            item["text"].append(
                "PAPER TEST / RAW "+side+
                "<br>Strategie M1: "+methods+
                "<br>Wejście na OPEN świecy UTC: "+escape(str(when))+
                f"<br>Świeca OPEN MID: {entry:.2f} pkt"+
                ("<br>SL: "+f"{stop:.2f}" if stop is not None else "")+
                ("<br>TP: "+f"{target:.2f}" if target is not None else "")+
                "<br>Otwarcie modelowane (nie broker); znane dopiero po zamknięciu świecy.")
        status=pos.get("status")
        if status not in ("CLOSED_TP","CLOSED_SL","CLOSED_TIMEOUT"):
            continue
        exit_time=_stamp(pos.get("closed_utc"))
        exit_value=_num(pos.get("exit_mid"))
        pnl=_num(pos.get("pnl_pts"))
        if (exit_time is None or exit_value is None or pnl is None or
                (lower is not None and exit_time<lower) or
                (upper is not None and exit_time>upper)):
            continue
        group=entries["GAIN" if pnl>0 else "LOSS"]
        group["x"].append(exit_time)
        group["y"].append(exit_value)
        group["labels"].append(f"CLOSE {pnl:+.2f} pkt")
        group["text"].append(
            "PAPER TEST RAW — "+escape(str(status))+
            "<br>Kierunek: "+side+
            "<br>Strategia M1: "+methods+
            "<br>Wyjście UTC: "+escape(str(exit_time))+
            f"<br>Wyjście MID: {exit_value:.2f} pkt"+
            f"<br>WYNIK po spread/slippage: {pnl:+.2f} pkt"+
            "<br>Wykonanie wirtualne, nie Capital.com.")
    for key,style in groups.items():
        group=entries[key]
        if not group["x"]:
            continue
        fig.add_trace(go.Scatter(
            x=group["x"],y=group["y"],text=group["labels"],
            customdata=group["text"],
            mode="markers+text",name=style["name"],
            textposition="top center" if key in ("LONG","GAIN","LOSS")
                         else "bottom center",
            textfont={"size":13,"color":style["color"]},
            cliponaxis=False,
            marker={"symbol":style["symbol"],"size":20,
                    "color":style["color"],
                    "line":{"width":2,"color":"#111827"}},
            hovertemplate="%{customdata}<extra></extra>",
        ))
    if isinstance(active,dict) and active.get("status")=="OPEN":
        for label,key,color in (
            ("🧪 RAW ENTRY", "entry_mid", "#55c9ff"),
            ("🧪 RAW STOP", "stop", "#ff6586"),
            ("🧪 RAW TARGET", "target", "#3dffb1"),
        ):
            price=_num(active.get(key))
            if price is None:
                continue
            fig.add_hline(y=price,line={"color":color,"width":2,
                                       "dash":"dash"},
                          annotation_text=f"{label} {price:.2f}",
                          annotation_font_color=color)
    return fig


def rows_for_journal(report, limit=60):
    """Read-only Polish owner journal, local Warsaw time and net points."""
    if (not isinstance(report,dict) or
            report.get("status")!="FORWARD_ONLY_RAW_M1_SIMULATION"):
        return []
    positions=(list(report.get("recent") or [])+
               list(report.get("invalidated_recent") or []))
    active=report.get("active")
    if isinstance(active,dict):
        positions.append(active)
    def local(t):
        x=_stamp(t)
        return x.tz_convert("Europe/Warsaw").strftime("%d.%m.%Y %H:%M") if x is not None else "—"
    out=[]
    positions.sort(key=lambda p:str(
        p.get("invalidated_utc") or p.get("closed_utc") or
        p.get("opened_utc") or p.get("setup_utc") or ""),
        reverse=True)
    for p in positions[:limit]:
        if not isinstance(p,dict):
            continue
        side=p.get("side")
        if side not in ("LONG","SHORT"):
            continue
        status=p.get("status")
        is_open=(status=="OPEN" or str(status).startswith("CLOSED_") or
                 (status=="INVALIDATED" and p.get("previous_status")=="OPEN"))
        pnl=_num(p.get("pnl_pts"))
        out.append({
            "Kierunek":side,
            "Status":status,
            "Strategia M1":", ".join(str(x) for x in (p.get("methods") or [])),
            "SETUP (Polska)":local(p.get("setup_utc")),
            "OPEN świecy (Polska)":local(p.get("entry_bar_open_utc")) if is_open else "—",
            "Potwierdzenie OPEN (Polska)":local(p.get("opened_utc")) if is_open else "—",
            "CLOSE (Polska)":local(p.get("closed_utc")),
            "Unieważniono (Polska)":local(p.get("invalidated_utc")),
            "Powód":p.get("invalidation_reason") or str(status),
            "Wejście (pkt)":_num(p.get("entry_mid")) if is_open else None,
            "SL":_num(p.get("stop")),
            "TP":_num(p.get("target")),
            "Wyjście (pkt)":_num(p.get("exit_mid")),
            "Zysk/strata netto (pkt)":round(pnl,2) if pnl is not None else None,
            "Przeszedł MTF":bool(p.get("after_mtf")),
        })
    return out
