"""Read-only position trails for the existing FOKU$ US500 candlestick terminal.

Draw historical price paths ONLY from genuine, archived CLOSED OHLC bars.
The entry/exit is backed by saved PAPER ledgers; the interior points are
archive candle closes, *not* recorded broker fills or a tick replay.
No trading inputs, broker orders, database writes, synthetic candles, or
changes to the original plot zoom, colors, WebSocket and strategy.
"""
from __future__ import annotations

from datetime import timezone
from html import escape
from math import isfinite

import pandas as pd

SOURCE="Capital.com DEMO REST"
DONE=frozenset(("CLOSED_SL","CLOSED_TP","CLOSED_TIMEOUT"))
TRACKED=DONE|frozenset(("OPEN","INVALIDATED"))
FRIENDLY_TF={"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}
MAX_DRAWN=3


def _utc(value):
    if value is None:
        return None
    try:
        stamp=pd.Timestamp(value)
    except (ValueError,TypeError,OverflowError):
        return None
    if pd.isna(stamp) or stamp.tzinfo is None:
        return None
    return stamp.tz_convert("UTC")


def _num(value):
    if value is None or isinstance(value,bool):
        return None
    try:
        result=float(value)
    except (ValueError,TypeError,OverflowError):
        return None
    return result if isfinite(result) else None


def _local(ts):
    return ts.tz_convert("Europe/Warsaw").strftime("%d.%m.%Y %H:%M:%S")


def _normalise(pos,lane):
    if not isinstance(pos,dict):
        return None
    side,status=pos.get("side"),pos.get("status")
    if side not in ("LONG","SHORT") or status not in TRACKED:
        return None
    if status=="INVALIDATED" and pos.get("previous_status")!="OPEN":
        return None
    if lane=="PAPER v3" and (pos.get("epic")!="US500"
                              or pos.get("source")!=SOURCE
                              or not pos.get("trade_id")):
        return None

    started=_utc(pos.get("entry_bar_open_utc") or
                 pos.get("entry_assumed_utc") or pos.get("opened_utc"))
    confirmed=_utc(pos.get("opened_utc"))
    entry=_num(pos.get("entry_mid"))
    if started is None or confirmed is None or entry is None or entry<=0:
        return None
    if started>confirmed or (confirmed-started)>pd.Timedelta(hours=1):
        return None

    if status in DONE:
        ending=_utc(pos.get("closed_utc"))
        exit_value=_num(pos.get("exit_mid"))
        net=_num(pos.get("pnl_pts"))
        if ending is None or exit_value is None or net is None or exit_value<=0:
            return None
    elif status=="INVALIDATED":
        ending=_utc(pos.get("invalidated_utc"))
        exit_value=None
        net=None
    else:
        ending=None
        exit_value=None
        net=None
    if ending is not None and ending<confirmed:
        return None

    if lane=="RAW M1":
        method=", ".join(str(v) for v in (pos.get("methods") or [])[:3]) or "RAW M1"
    elif lane=="MOMENTUM":
        method=str(pos.get("strategy") or "MOMENTUM M1")
    else:
        method=str(pos.get("strategy") or "AUTO PAPER")
    return {
        "lane":lane,"side":side,"status":status,
        "id":str(pos.get("trade_id") or (pos.get("setup_utc") or confirmed.isoformat()))[:36],
        "method":method[:80],
        "start":started,"confirmed":confirmed,"end":ending,
        "entry":entry,"exit":exit_value,"net":net,
        "stop":_num(pos.get("stop") if lane!="PAPER v3" else pos.get("stop_mid")),
        "target":_num(pos.get("target") if lane!="PAPER v3" else pos.get("target_mid")),
        "reason":str(pos.get("invalidation_reason") or "")[:60],
    }


def recorded_positions(payload):
    """Extract only VERIFIED OPEN/CLOSED (not PENDING/OBSERVE/SHADOW)."""
    if not isinstance(payload,dict):
        return []
    all_rows=[]
    tables=payload.get("tables")
    if isinstance(tables,dict):
        v3=tables.get("paper_positions_v3")
        if isinstance(v3,list):
            all_rows.extend(("PAPER v3",p) for p in v3)
    raw=payload.get("raw_m1_forward_paper_report")
    if isinstance(raw,dict) and raw.get("status")=="FORWARD_ONLY_RAW_M1_SIMULATION":
        history=raw.get("recent")
        invalid=raw.get("invalidated_recent")
        if isinstance(history,list):
            all_rows.extend(("RAW M1",p) for p in history)
        if isinstance(invalid,list):
            all_rows.extend(("RAW M1",p) for p in invalid)
        if isinstance(raw.get("active"),dict):
            all_rows.append(("RAW M1",raw["active"]))
    momentum=payload.get("momentum_paper_test")
    if isinstance(momentum,dict) and momentum.get("schema")==1:
        rows=momentum.get("closed")
        if isinstance(rows,list):
            all_rows.extend(("MOMENTUM",p) for p in rows)
        if isinstance(momentum.get("active"),dict):
            all_rows.append(("MOMENTUM",momentum["active"]))

    valid=[]
    seen=set()
    for lane,p in all_rows:
        obj=_normalise(p,lane)
        if obj is None:
            continue
        key=(obj["lane"],obj["id"],obj["side"],obj["start"])
        if key in seen:
            continue
        seen.add(key)
        valid.append(obj)
    return valid


def _hover(pos,stamp,price,*,final=False):
    direction=1 if pos["side"]=="LONG" else -1
    gross=(price-pos["entry"])*direction
    plain=(
        f"{escape(pos['lane'])} • {pos['side']}"
        f"<br>Strategia: {escape(pos['method'])}"
        f"<br>Godzina polska: {_local(stamp)}"
        f"<br>Wejście MID: {pos['entry']:.2f} pkt"
        f"<br>Cena obserwowana: {price:.2f} pkt"
        f"<br>Ruch ceny od wejścia: {gross:+.2f} pkt (bez kosztów)"
    )
    if final:
        plain+=(
            f"<br>MODEL CLOSE: {pos['exit']:.2f} pkt"
            f"<br>WYNIK NETTO: {pos['net']:+.2f} pkt"
            f"<br>Status: {pos['status']}"
            "<br>Dokładny moment intrabar TP/SL nie jest znany."
        )
    else:
        plain+="<br>Zweryfikowane zamknięcie świecy; nie tick / broker fill."
    return plain


def _events(fig, pos, frame, lo, hi, step, *, live_quotes=None):
    """One trade; return (drawn, gap_count, observed_samples).

    Segments never bridge missing candles. TP/SL is a dotted model endpoint,
    not a fabricated intra-minute price path.
    """
    import plotly.graph_objects as go

    start=pos["start"]
    end=pos["end"] or frame.index[-1]
    if start>hi or end<lo or start>end:
        return False,0,0

    final=pos["status"] in DONE
    # Exact source candle closes during trade lifespan. On the exit candle
    # the bar CLOSE is not necessarily the price where SL/TP was hit.
    # Therefore it is excluded and replaced by a distinct model endpoint.
    terminal=pos["status"] in DONE or pos["status"]=="INVALIDATED"
    available=frame.loc[(frame.index>start)&
                        (frame.index<end if terminal else frame.index<=end)]
    if available.empty and not final:
        return False,0,0
    if available.empty and final:
        # If an entry closed on the first candle, only a fill and modeled
        # exit are known, not a traversed price route. Existing markers
        # represent it; don't invent an interpolated intra-candle line.
        return False,0,0

    half_step=pd.Timedelta(seconds=step+2)
    color={"gain":"#17c987","loss":"#f04860"}
    segments={k:{"x":[],"y":[],"hover":[]} for k in color}
    last_time,last_price=start,pos["entry"]
    gap_count=0
    observed=0
    last_verified=None
    for stamp,row in available.iterrows():
        px=_num(row.get("Close"))
        high=_num(row.get("High"))
        low=_num(row.get("Low"))
        if px is None or low is None or high is None or not 0<low<=px<=high:
            # No inferred fill from a corrupt/unverified OHLC candle.
            gap_count+=1
            last_time,last_price=None,None
            continue
        stamp=_utc(stamp)
        if stamp is None:
            continue
        observed+=1
        last_verified=stamp,px
        if last_time is not None and pd.Timedelta(0)<stamp-last_time<=half_step:
            is_gain=(px-pos["entry"])*(1 if pos["side"]=="LONG" else -1)>=0
            group=segments["gain" if is_gain else "loss"]
            group["x"].extend((last_time,stamp,None))
            group["y"].extend((last_price,px,None))
            group["hover"].extend((
                _hover(pos,last_time,last_price),_hover(pos,stamp,px),None))
        else:
            gap_count+=1
        last_time,last_price=stamp,px

    if observed==0:
        return False,gap_count,0

    for key,entry in segments.items():
        if not entry["x"]:
            continue
        fig.add_trace(go.Scatter(
            x=entry["x"],y=entry["y"],customdata=entry["hover"],
            mode="lines",name=f"RUCH {pos['lane']} {pos['side']}",
            showlegend=False,connectgaps=False,
            line={"color":color[key],"width":3.5},
            opacity=.88,hovertemplate="%{customdata}<extra></extra>",
        ))

    # Only levels inside the trade's lifetime (rather than giant lines
    # across the whole screen). Persistent in the archive while OHLC exists.
    last_time_in_view=pos["end"] or frame.index[-1]
    level_end=min(last_time_in_view,hi)
    level_start=max(start,lo)
    if level_start<level_end:
        for name,price,stroke in (
            ("ENTRY",pos["entry"],"#a8d8ff"),
            ("SL",pos["stop"],"#e96579"),
            ("TP",pos["target"],"#2dd4a1"),
        ):
            if price is None or price<=0:
                continue
            fig.add_trace(go.Scatter(
                x=[level_start,level_end],y=[price,price],
                mode="lines",name=f"{pos['lane']} {name}",
                line={"color":stroke,"width":1.5,"dash":"dot"},
                opacity=.55,showlegend=False,
                hovertemplate=(
                    f"{escape(pos['lane'])} {name}: {price:.2f} pkt"
                    "<extra></extra>"),
            ))

    # Do not connect a gap. When the modeled exit was hit intrabar, show
    # a SHORT DOTTED connection from the last verified candle (if adjacent).
    if final and last_verified is not None:
        when,price=last_verified
        if (pos["end"] is not None and pos["exit"] is not None and
                pd.Timedelta(0)<=pos["end"]-when<=half_step):
            fig.add_trace(go.Scatter(
                x=[when,pos["end"]],y=[price,pos["exit"]],
                mode="lines",name="MODEL WYJŚCIA (TP/SL/TIMEOUT)",
                line={"color":"#d6a546","width":2,"dash":"dash"},
                opacity=.9,showlegend=False,
                customdata=[
                    _hover(pos,when,price),
                    _hover(pos,pos["end"],pos["exit"],final=True),
                ],hovertemplate="%{customdata}<extra></extra>",
            ))

    # Transient 5-second quote overlay for *currently OPEN* PAPER only.
    # These are observed BROKER MID snapshots, NOT fills, and never carried
    # into a historical chart or counted in the simulated P&L.
    if pos["status"]=="OPEN" and isinstance(live_quotes,list) and last_verified:
        point_t,point_price=last_verified
        x=[point_t]
        y=[point_price]
        for item in live_quotes[-24:]:
            if not isinstance(item,dict):
                continue
            ts=_utc(item.get("time"))
            mid=_num(item.get("mid"))
            if (ts is None or mid is None or mid<=0 or ts<=x[-1]
                    or ts>hi or ts<lo or ts-x[-1]>pd.Timedelta(seconds=120)):
                continue
            x.append(ts)
            y.append(mid)
        if len(x)>1:
            fig.add_trace(go.Scatter(
                x=x,y=y,mode="lines",name="BIEŻĄCY MID (PODGLĄD)",
                showlegend=False,
                line={"color":"#ebc44a","width":2,"dash":"dot"},
                opacity=.9,
                hovertemplate="BIEŻĄCY BID/ASK MID (podgląd, nie fill)<br>"
                              "%{x}<br>%{y:.2f} pkt<extra></extra>",
            ))
    return True,gap_count,observed


def annotate_position_trails(fig, frame, payload, *, choice="M1",
                             viewport=None, max_positions=MAX_DRAWN,
                             live_quotes=None):
    """Overlay tracked PAPER movement on existing Plotly candlesticks.

    For all timeframes, points are *closed candles of that timeframe*, not
    a fake tick chart. On M1 this best resembles the actual paper lifecycle.
    """
    if (choice not in FRIENDLY_TF or not isinstance(frame,pd.DataFrame)
            or frame.empty or not isinstance(frame.index,pd.DatetimeIndex)
            or frame.index.tz is None or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing or
            not {"Close","High","Low"}.issubset(frame.columns)
            or not isinstance(payload,dict)):
        return {"drawn":0,"gaps":0,"samples":0,"available":0}
    if not isinstance(max_positions,int) or not 1<=max_positions<=6:
        raise ValueError("Chart path cap must be 1..6")
    lo=_utc(viewport[0]) if isinstance(viewport,(tuple,list)) and len(viewport)==2 else frame.index[0]
    hi=_utc(viewport[1]) if isinstance(viewport,(tuple,list)) and len(viewport)==2 else frame.index[-1]
    if lo is None or hi is None or lo>hi:
        return {"drawn":0,"gaps":0,"samples":0,"available":0}

    # Try OPEN first; then up to three most recent recorded positions whose
    # lifetime intersects the user's actual candle window.
    available=[
        p for p in recorded_positions(payload)
        if p["start"]<=hi and (p["end"] is None or p["end"]>=lo)
    ]
    available.sort(key=lambda p:(
        p["status"]=="OPEN",p["end"] or frame.index[-1],p["start"]),reverse=True)
    total=0
    gaps=0
    samples=0
    for p in available[:max_positions]:
        is_live=p["status"]=="OPEN" and p["end"] is None
        drawn,missing,count=_events(
            fig,p,frame,lo,hi,FRIENDLY_TF[choice],
            live_quotes=live_quotes if is_live else None)
        total+=int(drawn)
        gaps+=missing
        samples+=count
    return {"drawn":total,"gaps":gaps,"samples":samples,"available":len(available)}
