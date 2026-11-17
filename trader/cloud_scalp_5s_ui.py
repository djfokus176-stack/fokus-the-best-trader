"""Owner's 5-second read-only BID/ASK cloud widget.

Streamlit accesses ONLY Supabase; the Capital.com API key, password and
session remain on the dedicated Northflank worker. The 5-second refresh
does not create candles, place positions or infer profitable scalps.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .remote_checkpoint import RemoteCheckpoint, RemoteError


def assess_quote_snapshot(record, *, now=None):
    """Fail closed on stale/unknown/closed quotes; do not fabricate a tick."""
    if not isinstance(record,dict) or record.get("epic")!="US500" or (
            record.get("source")!="Capital.com DEMO REST"):
        raise ValueError("SCALP 5S: unexpected source/instrument")
    try:
        bid=float(record["bid"]);ask=float(record["ask"])
        mid=float(record["mid"]);spread=float(record["spread"])
        delay=float(record.get("delay_seconds",0))
    except (TypeError,ValueError,KeyError,OverflowError):
        raise ValueError("SCALP 5S: invalid price") from None
    if (not all(isfinite(x) for x in (bid,ask,mid,spread,delay))
            or bid<=0 or ask<bid or mid<=0 or spread<0 or
            abs((ask-bid)-spread)>0.001):
        raise ValueError("SCALP 5S: inconsistent BID/ASK")
    try:
        received=pd.Timestamp(record["received_utc"])
        if pd.isna(received) or received.tzinfo is None:
            raise ValueError()
        received=received.tz_convert("UTC")
        current=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
        if pd.isna(current) or current.tzinfo is None:
            raise ValueError()
        current=current.tz_convert("UTC")
        seconds=(current-received).total_seconds()
    except (ValueError,TypeError,OverflowError):
        raise ValueError("SCALP 5S: bad UTC") from None
    status=str(record.get("broker_status","UNKNOWN"))
    raw=record.get("samples") or []
    # The private Supabase schema has a historical fixed source key
    # 'Capital.com DEMO REST'. A STREAMING_ACTIVE row MUST carry its
    # explicit provenance marker, or it is not accepted as an active feed.
    stream=(isinstance(raw,list) and bool(raw)
            and isinstance(raw[-1],dict)
            and raw[-1].get("transport")=="CAPITAL_WS_V1")
    vendor_ok=False
    if stream:
        try:
            vendor=pd.Timestamp(record["broker_update_utc"])
            if pd.isna(vendor) or vendor.tzinfo is None:
                raise ValueError()
            age_vendor=(current-vendor.tz_convert("UTC")).total_seconds()
            vendor_ok=-2<=age_vendor<=15
        except (TypeError,ValueError,OverflowError,KeyError):
            vendor_ok=False
    is_fresh=(record.get("fresh") is True and delay==0
              and -2<=seconds<=12
              and ((status=="TRADEABLE" and not stream)
                   or (status=="STREAMING_ACTIVE" and stream and vendor_ok)))
    samples=[]
    if not isinstance(raw,list) or len(raw)>24:
        raise ValueError("SCALP 5S: corrupt samples")
    for sample in raw:
        if not isinstance(sample,dict):
            raise ValueError("SCALP 5S: corrupt sample")
        try:
            stamp=pd.Timestamp(sample["utc"])
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise ValueError()
            b=float(sample["bid"]);a=float(sample["ask"])
            if not isfinite(b) or not isfinite(a) or b<=0 or a<b:
                raise ValueError()
        except (ValueError,TypeError,KeyError,OverflowError):
            raise ValueError("SCALP 5S: invalid sample") from None
        samples.append({"time":stamp.tz_convert("UTC"),"mid":(a+b)/2})
    return {"bid":bid,"ask":ask,"mid":mid,"spread":spread,
            "age_seconds":round(seconds,1),"broker_status":status,
            "fresh":is_fresh,"samples":samples,
            "broker_update_utc":record.get("broker_update_utc"),
            "received_utc":received.isoformat(),"trade_permission":"WAIT"}


@st.fragment(run_every="5s")
def render_cloud_scalp_5s(secret_fn):
    st.markdown("#### ⚡ US500 — CENA / BID–ASK CO 5 SEKUND")
    st.caption(
        "Panel odświeża dane z Supabase co ~5 s. Nowy transport "
        "Capital WebSocket przesyła rzeczywiste zdarzenia cenowe; "
        "REST pozostaje do świec zamkniętych i PAPER. "
        "Brak nowych ticków = brak sztucznego ruchu. "
        "Przeglądarka NIE loguje się do brokera.")
    url=secret_fn("FOKUS_SUPABASE_URL")
    key=secret_fn("FOKUS_SUPABASE_SECRET_KEY")
    if not url or not key:
        st.warning("Brak Secrets Supabase w terminalu. "
                   "Nie oznacza to awarii workera Northflank.")
        return
    try:
        remote=RemoteCheckpoint(url,key)
        record=remote.fetch_live_quote("US500")
        if record is None:
            st.info("Collector 5s nie zapisał jeszcze pierwszej ceny. "
                    "Potrzebne jest otwarcie rynku i przygotowana "
                    "prywatna tabela fokus_live_quotes.")
            return
        result=assess_quote_snapshot(record)
    except (RemoteError,ValueError,KeyError,TypeError,OverflowError,OSError):
        st.warning("Brak poprawnego podglądu 5s w Supabase. "
                   "Możliwy brak tabeli fokus_live_quotes lub brak "
                   "świeżego odczytu workera. M15 pozostaje osobnym archiwum.")
        return
    left,mid,right=st.columns(3)
    left.metric("BID (LIVE)" if result["fresh"] else
                "OSTATNI BID — NIE LIVE",f'{result["bid"]:.2f}')
    mid.metric("ASK (LIVE)" if result["fresh"] else
               "OSTATNI ASK — NIE LIVE",f'{result["ask"]:.2f}')
    right.metric("Spread (pkt)",f'{result["spread"]:.2f}')
    transport="WebSocket" if record.get("samples") and isinstance(
        record["samples"][-1],dict) and (
        record["samples"][-1].get("transport")=="CAPITAL_WS_V1") else "REST"
    st.caption("Broker: "+result["broker_status"]+" | Transport: "+transport+
               " | Ostatnia próba UTC: "+result["received_utc"]+
               " | Wiek: "+str(result["age_seconds"])+" s")
    if result["fresh"]:
        st.success("Aktualny odczyt BID/ASK (nie sygnał scalpingowy).")
    else:
        st.warning("WAIT — brak aktualnego, nieopóźnionego BID/ASK. "
                   "Nie wyciągaj wniosków z ostatniej ceny.")
    history=result["samples"]
    if not result["fresh"] and len(history)>=2:
        st.caption("Wykres ostatnich 24 próbek jest ukryty, ponieważ "
                   "aktualnego BID/ASK nie potwierdzono. Stare notowania "
                   "nie powinny wyglądać na ruch rynku.")
    if result["fresh"] and len(history)>=2:
        df=pd.DataFrame(history)
        chart=go.Figure(go.Scatter(x=df["time"],y=df["mid"],
                                   mode="lines+markers",
                                   name="Średnia BID/ASK",line={"width":1.8}))
        chart.update_layout(
            height=235,template="plotly_dark",
            paper_bgcolor="#111a2d",plot_bgcolor="#111a2d",
            margin={"l":10,"r":10,"t":12,"b":8})
        st.plotly_chart(chart,use_container_width=True,
                        key="fokus_cloud_5s_chart")
        st.caption("Ostatnie maksymalnie 24 rzeczywiste obserwacje. "
                   "WebSocket może dostarczać je znacznie częściej niż "
                   "co 5 s, więc to NIE musi być historia 2 minut. "
                   "Brak interpolacji i fikcyjnych knotów.")
