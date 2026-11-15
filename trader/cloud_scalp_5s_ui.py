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
    is_fresh=(record.get("fresh") is True and status=="TRADEABLE"
              and delay==0 and -2<=seconds<=12)
    samples=[]
    raw=record.get("samples") or []
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
        "Odczyt co ok. 5 s z chmury — NIE gwarantuje nowego ticka. "
        "Worker próbuje aktualizacji co 5 s POMIĘDZY pełnymi skanami M1. "
        "Bez API Capital.com w przeglądarce, bez automatycznych transakcji.")
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
    left.metric("BID",f'{result["bid"]:.2f}')
    mid.metric("ASK",f'{result["ask"]:.2f}')
    right.metric("Spread (pkt)",f'{result["spread"]:.2f}')
    st.caption("Broker: "+result["broker_status"]+
               " | Ostatnia próba UTC: "+result["received_utc"]+
               " | Wiek: "+str(result["age_seconds"])+" s")
    if result["fresh"]:
        st.success("Aktualny odczyt BID/ASK (nie sygnał scalpingowy).")
    else:
        st.warning("WAIT — brak aktualnego, nieopóźnionego BID/ASK. "
                   "Nie wyciągaj wniosków z ostatniej ceny.")
    history=result["samples"]
    if len(history)>=2:
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
        st.caption("Ostatnie maksymalnie 24 pobrane próbki (~2 min). "
                   "To punkty obserwacji REST, NIE ticki giełdowe "
                   "ani świece pięciosekundowe.")
