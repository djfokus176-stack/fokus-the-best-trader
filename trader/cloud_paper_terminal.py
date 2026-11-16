"""Read-only cloud terminal from worker's persisted M15 and checkpoint.

This module NEVER authenticates against Capital.com directly. The service's
permanent, private credentials belong to the Northflank worker. Streamlit
requires only its own server-side Supabase read credentials to show results.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .remote_checkpoint import RemoteCheckpoint, RemoteError
from .paper_method_labels import method_attribution
from .paper_display import annotate_open_paper, annotate_paper_history
from .cloud_m15_live_overlay import (cloud_quote_overlay,m15_cache_due,
                                     closed_m15_lag)


def _parse_utc(value):
    if not value:
        return None
    try:
        ts=pd.Timestamp(value)
        if pd.isna(ts) or ts.tzinfo is None:
            return None
        return ts.tz_convert("UTC")
    except (ValueError,TypeError,OverflowError):
        return None


def cloud_terminal_summary(version, payload, frame, *, now=None):
    """Pure summary. A checkpoint is not proof of valid broker quotes."""
    if not isinstance(payload,dict) or not isinstance(frame,pd.DataFrame):
        raise ValueError("Nieprawidlowy cloud checkpoint lub OHLC.")
    meta=payload.get("meta") or {}
    if not isinstance(meta,dict):
        raise ValueError("Nieprawidlowe cloud meta.")
    if meta.get("epic") not in (None,"US500"):
        raise ValueError("Inny instrument w cloud checkpoint.")
    source=meta.get("source","BRAK")
    if source not in ("Capital.com DEMO REST","BRAK"):
        raise ValueError("Oczekiwano danych Capital.com DEMO REST.")
    if not frame.empty:
        needed=("Open","High","Low","Close","Spread")
        if (not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None
                or frame.index.has_duplicates or not frame.index.is_monotonic_increasing
                or not set(needed).issubset(frame.columns)):
            raise ValueError("Cloud M15 wymaga unikalnych UTC i OHLC+Spread.")
        vals=frame.loc[:,needed].apply(pd.to_numeric,errors="coerce")
        if (vals.isna().any().any() or not vals.map(
                lambda x: pd.notna(x) and float("-inf")<x<float("inf")
                ).all().all()):
            raise ValueError("Niefinitywne OHLC/Spread w archiwum.")
        if (vals["Low"].le(0).any() or
                vals["High"].lt(vals[["Open","Low","Close"]].max(axis=1)).any() or
                vals["Low"].gt(vals[["Open","High","Close"]].min(axis=1)).any()
                or vals["Spread"].lt(0).any()):
            raise ValueError("Niespojny OHLC/Spread w archiwum.")
    current=_parse_utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if current is None:
        raise ValueError("Nieprawidlowy czas inspekcji.")
    last_scan=_parse_utc(meta.get("last_scan_utc"))
    last_m15=frame.index[-1].tz_convert("UTC") if len(frame) else None
    age=(round((current-last_scan).total_seconds()/60,1)
         if last_scan is not None else None)
    return {
        "version":version,
        "last_scan_utc":last_scan.isoformat() if last_scan is not None else None,
        "last_m15_utc":last_m15.isoformat() if last_m15 is not None else None,
        "age_minutes":age,
        "worker_summary":str(meta.get("last_scan_summary","BRAK"))[:300],
        "bars":len(frame),
        "backfill_enabled":meta.get("candle_backfill_enabled") is True,
        "cloud_online_confirmed":bool(age is not None and 0<=age<=10),
        "trade_permission":"WAIT",
        "no_direct_capital_login":True,
    }

def cloud_paper_positions(payload, frame):
    """Read-only rows from one checkpoint; never infer unrecorded signals.

    The cloud M15 chart may show M1/M5/H1 actual PAPER markers on its time
    axis. Exclude off-chart events to prevent Plotly from re-scaling across
    months of old ledger history.
    """
    tables=payload.get("tables") if isinstance(payload,dict) else None
    raw=tables.get("paper_positions_v3") if isinstance(tables,dict) else None
    if not isinstance(raw,list):
        return [], []
    valid=[]
    for pos in raw:
        if (not isinstance(pos,dict) or
                pos.get("source")!="Capital.com DEMO REST" or
                pos.get("epic")!="US500" or
                pos.get("side") not in ("LONG","SHORT") or
                pos.get("status") not in
                    ("PENDING","OPEN","CLOSED_SL","CLOSED_TP",
                     "CLOSED_TIMEOUT","INVALIDATED")):
            continue
        valid.append(pos)
    valid.sort(key=lambda p: str(p.get("created_utc") or ""),reverse=True)
    if frame.empty:
        return valid[:25], []
    start,end=frame.index[0],frame.index[-1]+pd.Timedelta(minutes=15)
    chart_rows=[]
    for pos in valid[:80]:
        opened=_parse_utc(pos.get("opened_utc"))
        closed=_parse_utc(pos.get("closed_utc"))
        if ((opened is not None and start<=opened<=end) or
                (closed is not None and start<=closed<=end)):
            chart_rows.append(pos)
    return valid[:25],chart_rows


@st.fragment(run_every="5s")
def render_cloud_terminal(secret_fn):
    """Owner-only M15 archive + live REST BID/ASK overlay; no Capital auth.

    Fragment updates the PRICE OVERLAY about every five seconds only while
    browser is open. Closed M15 and checkpoint load about every 60 seconds.
    Worker clocks, AUTO and PAPER remain completely independent.
    """
    st.markdown("#### ☁️ US500 — CLOUD M15 + CENA BID/ASK ~5S")
    st.caption(
        "Świece: tylko ZAMKNIĘTE M15, aktualizowane z Supabase co ok. 60 s. "
        "Żółty ślad: osobne odczyty BID/ASK z REST, odświeżane ok. 5 s "
        "gdy strona jest otwarta. NIE są to ticki ani świece 5S. "
        "Streamlit NIE loguje się do brokera, tylko czyta chmurę.")
    url=secret_fn("FOKUS_SUPABASE_URL")
    key=secret_fn("FOKUS_SUPABASE_SECRET_KEY")
    if not url or not key:
        st.warning("Brak prywatnych Secrets Supabase w Streamlit. "
                   "Nie oznacza to awarii niezależnego workera Northflank.")
        return
    try:
        remote=RemoteCheckpoint(url,key)
        cache=st.session_state.get("_fokus_cloud_m15_cache_v2")
        if (not isinstance(cache,dict) or cache.get("url")!=url
                or m15_cache_due(cache)):
            version,payload=remote.fetch()
            frame=remote.fetch_candles("US500","MINUTE_15",limit=180)
            audit=cloud_terminal_summary(version,payload,frame)
            # Per-BROWSER session cache only; never put credentials in it.
            st.session_state["_fokus_cloud_m15_cache_v2"]={
                "url":url,"version":version,"payload":payload,"frame":frame,
                "fetched_utc":pd.Timestamp.now(tz="UTC").isoformat()}
        else:
            version,payload,frame=(cache["version"],cache["payload"],cache["frame"])
            audit=cloud_terminal_summary(version,payload,frame)
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        st.session_state.pop("_fokus_cloud_m15_cache_v2",None)
        st.error("Nie udało się odczytać checkpointu lub archiwum M15. "
                 "Nie przedstawiam niezweryfikowanego cache jako aktualnego. "
                 "Sprawdź STATUS/API i Northflank.")
        return
    # Price polling is intentionally independent of a healthy M15 archive.
    # A broken/stale quote must NEVER erase the historical chart or be
    # drawn as if the price were tradable.
    try:
        overlay=cloud_quote_overlay(remote.fetch_live_quote("US500"))
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        overlay={"visible":False,"broker_status":"UNKNOWN","age_seconds":None,
                 "reason":"Nie udało się odczytać aktualnego BID/ASK.",
                 "points":[]}
    x,y,z=st.columns(3)
    x.metric("Checkpoint",str(audit["version"]))
    y.metric("Zapisane M15",str(audit["bars"]))
    z.metric("Wiek checkpointu",str(audit["age_minutes"])+" min"
             if audit["age_minutes"] is not None else "BRAK")
    if audit["cloud_online_confirmed"]:
        st.caption("Checkpoint zapisano niedawno. Nie dowodzi to otwarcia "
                   "rynku ani poprawności każdej świecy M15.")
    else:
        st.warning("Checkpoint nie jest świeży lub jego daty nie potwierdzono. "
                   "Sprawdź Northflank; nie twierdzę, że worker teraz działa.")
    if overlay["visible"]:
        st.metric("🟡 BIEŻĄCY MID BID/ASK (REST)",f'{overlay["mid"]:.2f} pkt')
        st.caption(
            f'BID {overlay["bid"]:.2f} | ASK {overlay["ask"]:.2f} | '
            f'Spread {overlay["spread"]:.2f} pkt | '
            f'Broker {overlay["broker_status"]} | '
            f'Wiek odczytu {overlay["age_seconds"]} s. '
            "To próbki API, nie ticki ani cena wykonanego zlecenia.")
    else:
        st.warning("⚪ BRAK AKTUALNEJ CENY 5S: "+overlay["reason"]+
                   " | Broker: "+str(overlay["broker_status"])+
                   " | Wiek: "+str(overlay["age_seconds"])+
                   " s. Ostatnie M15 to wyłącznie historia.")
    st.caption("Ostatni zapis skanera UTC: "+
               str(audit["last_scan_utc"] or "BRAK")+
               " | Ostatnia M15 w archiwum UTC: "+
               str(audit["last_m15_utc"] or "BRAK"))
    st.caption("Ostatnia informacja workera (nie tej przeglądarki): "+
               audit["worker_summary"])
    recent_paper,chart_paper=cloud_paper_positions(payload,frame)
    if recent_paper:
        active=next((p for p in recent_paper
                     if p.get("status") in ("OPEN","PENDING")),None)
        if active:
            origin=method_attribution(active)
            st.info(
                "🧪 POZYCJA PAPER "+str(active["status"])+" | "+
                str(active["side"])+" | "+origin["label"]+
                " | TF="+str(active.get("timeframe","BRAK"))+
                " | ID="+str(active.get("trade_id","BRAK"))[:10]+
                " — symulacja odtwarzana ze świec, bez zlecenia Capital.com.")
        st.markdown("##### 📋 OSTATNIE POZYCJE PAPER — TRYB I METODA")
        st.dataframe(pd.DataFrame([{
            "Kierunek":p["side"],"Status":p["status"],
            "Tryb":method_attribution(p)["mode"],
            "Metoda":method_attribution(p)["method"],
            "Interwał":str(p.get("timeframe","BRAK")),
            "Czas OPEN UTC":str(p.get("opened_utc") or "BRAK"),
            "Wynik pkt":p.get("pnl_pts"),
            "ID":str(p.get("trade_id","BRAK"))[:12],
        } for p in recent_paper[:12]]),
        hide_index=True,use_container_width=True)
        st.caption("AUTO oznaczam tylko wtedy, gdy pochodzi z powodu sygnału "
                   "zapisanym przy tej pozycji. Starszy wpis bez dowodu "
                   "pozostaje jako NIEUSTALONY / POJEDYNCZY.")
    else:
        st.caption("W checkpointcie brak zarejestrowanych pozycji PAPER US500; "
                   "nie wyświetlam wymyślonych LONG/SHORT.")
    if frame.empty:
        st.info("W Supabase nie ma jeszcze świec M15 do wyświetlenia.")
        return
    candles=go.Figure(go.Candlestick(
        x=frame.index,open=frame.Open,high=frame.High,
        low=frame.Low,close=frame.Close,name="US500 M15 CLOUD"))
    # Only validated fresh DEMO quote points, never synthetic candles.
    if overlay["visible"]:
        points=overlay["points"]
        if points:
            candles.add_trace(go.Scatter(
                x=[p["time"] for p in points],
                y=[p["mid"] for p in points],
                mode="lines+markers" if len(points)>1 else "markers",
                name="🟡 MID BID/ASK ~5S (REST)",
                line={"color":"#f5c24b","width":2.6},
                marker={"size":7,"color":"#f5c24b"},
                hovertemplate="REST %{x}<br>MID: %{y:.2f}<extra></extra>"))
        candles.add_hline(
            y=float(overlay["mid"]),line_color="#f5c24b",
            line_dash="dot",opacity=.65,
            annotation_text=f'BID/ASK MID {overlay["mid"]:.2f}',
            annotation_position="top left")
    # Exact OPEN/CLOSE PAPER from the checkpoint, NEVER watch markers or
    # signals inferred from OHLC. M1 PAPER may appear on the M15 time axis.
    annotate_paper_history(candles,chart_paper,
                           "US500","Capital.com DEMO REST",None)
    open_row=next((p for p in recent_paper if p.get("status")=="OPEN"),None)
    if open_row is not None:
        annotate_open_paper(candles,open_row)
    candles.update_layout(
        height=410,xaxis_rangeslider_visible=False,template="plotly_dark",
        uirevision="fokus_cloud_m15_live_v2",
        paper_bgcolor="#111a2d",plot_bgcolor="#111a2d",
        margin={"l":10,"r":10,"t":15,"b":10})
    st.plotly_chart(candles,use_container_width=True,
                    key="cloud_worker_m15_chart")
    if overlay["visible"]:
        lag=closed_m15_lag(frame)
        if lag is not None and lag>35:
            st.warning(
                f'⚠️ Bieżące ceny są dostępne, ale ostatnia archiwalna '
                f'M15 ma {lag:.1f} min. Sprawdź zapis zamkniętych świec '
                'w Northflank/Supabase; checkpoint nie gwarantuje OHLC.')
    st.caption("Zielone/czerwone świece: HISTORYCZNE M15. Żółta linia i "
               "punkty: jedynie ŚWIEŻE obserwacje BID/ASK REST (~5 s, "
               "do 24 punktów), a nie ticki/świece. Trójkąty i kwadraty: "
               "WYŁĄCZNIE zapisane PAPER OPEN/CLOSED z checkpointu "
               "(także M1), po najechaniu AUTO → metoda, TF, ID, wynik. "
               "Wykres nie tworzy nowych transakcji ani brokerowych filli.")
