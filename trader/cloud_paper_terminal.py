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


@st.fragment(run_every="60s")
def render_cloud_terminal(secret_fn):
    """Owner-only automatic cloud history preview, not a broker LIVE chart."""
    st.markdown("#### ☁️ US500 — ARCHIWUM CLOUD M15 (SUPABASE)")
    st.caption(
        "Aktualizowane tylko gdy terminal jest otwarty. Przegladarka NIE "
        "loguje sie do Capital.com; calodobowy worker Northflank dziala "
        "osobno i ma wlasne Secrets. Dane sa archiwalne M15, nie "
        "pięciosekundowym LIVE BID/OFFER.")
    if not secret_fn("FOKUS_SUPABASE_URL") or not secret_fn("FOKUS_SUPABASE_SECRET_KEY"):
        st.warning("Brak prywatnych Secrets Supabase w Streamlit. "
                   "Nie oznacza to awarii niezaleznego workera Northflank.")
        return
    try:
        remote=RemoteCheckpoint(secret_fn("FOKUS_SUPABASE_URL"),
                                secret_fn("FOKUS_SUPABASE_SECRET_KEY"))
        version,payload=remote.fetch()
        frame=remote.fetch_candles("US500","MINUTE_15",limit=180)
        audit=cloud_terminal_summary(version,payload,frame)
    except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
        st.error("Nie udało się odczytać checkpointu lub archiwum "
                 "M15 z Supabase. To błąd PODGLĄDU, nie dowód awarii "
                 "workera Northflank. Sprawdź zakładkę STATUS/API.")
        return
    x,y,z=st.columns(3)
    x.metric("Checkpoint",str(audit["version"]))
    y.metric("Zapisane M15",str(audit["bars"]))
    z.metric("Wiek checkpointu",str(audit["age_minutes"])+" min"
             if audit["age_minutes"] is not None else "BRAK")
    if audit["cloud_online_confirmed"]:
        st.success("Zapis checkpointu jest świeży. To nie potwierdza "
                   "kompletności wszystkich świec ani otwarcia rynku.")
    else:
        st.warning("Checkpoint nie jest świeży lub jego daty nie potwierdzono. "
                   "Sprawdź Northflank; nie twierdzę, że worker teraz działa.")
    st.caption("Ostatni zapis skanera UTC: "+
               str(audit["last_scan_utc"] or "BRAK")+
               " | Ostatnia M15 w archiwum UTC: "+
               str(audit["last_m15_utc"] or "BRAK"))
    st.caption("Ostatnia informacja workera (nie tej przeglądarki): "+
               audit["worker_summary"])
    if frame.empty:
        st.info("W Supabase nie ma jeszcze świec M15 do wyświetlenia.")
        return
    candles=go.Figure(go.Candlestick(
        x=frame.index,open=frame.Open,high=frame.High,
        low=frame.Low,close=frame.Close,name="US500 M15 CLOUD"))
    candles.update_layout(
        height=410,xaxis_rangeslider_visible=False,template="plotly_dark",
        paper_bgcolor="#111a2d",plot_bgcolor="#111a2d",
        margin={"l":10,"r":10,"t":15,"b":10})
    st.plotly_chart(candles,use_container_width=True,
                    key="cloud_worker_m15_chart")
    st.caption("Wyłącznie historia potwierdzonych M15 z tabeli cloud, "
               "nie ceny wykonalne BID/ASK. Brak danych nie oznacza sygnału; "
               "AUTO oraz WAVE nie otrzymują tu żadnych nowych decyzji.")
