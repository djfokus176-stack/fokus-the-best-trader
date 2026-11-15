"""FOKU$ 3F standalone Streamlit RESEARCH view; no broker actions."""
from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from .remote_checkpoint import RemoteCheckpoint,RemoteError
from .fokus_3f import NAME,run_3f_replay,research_scorecard,RESOLVED
from .wave_reversal_eval import read_wave_m15_csv


def _performance_by_period(log):
    """Descriptive within-sample statistics; not an OOS claim."""
    if log is None or log.empty:return pd.DataFrame()
    df=log.copy()
    df["year"]=pd.to_datetime(df["signal_utc"],utc=True).dt.year
    rows=[]
    for (period,year,side),subset in df.groupby(
            ["sample","year","research_side"],sort=True):
        closed=subset[subset["status"].isin(RESOLVED)].copy()
        pnl=pd.to_numeric(closed["pnl_pts"],errors="coerce").dropna()
        curve=pnl.cumsum()
        peak=curve.cummax().clip(lower=0)
        loss=-pnl[pnl<0].sum()
        rows.append({
            "Próba":period,"Rok":int(year),"Kierunek":side,
            "Sygnały":len(subset),"Rozliczenia":len(pnl),
            "Skuteczność %":round(100*(pnl>0).mean(),1) if len(pnl) else None,
            "Netto pkt":round(float(pnl.sum()),2) if len(pnl) else None,
            "Średnio pkt":round(float(pnl.mean()),3) if len(pnl) else None,
            "Profit Factor":round(float(pnl[pnl>0].sum()/loss),3)
                if len(pnl)>=30 and loss>0 else None,
            "Max DD pkt":round(float((peak-curve).max()),2)
                if len(pnl) else None,
            "Ocena":"BADANIE; BEZ DOWODU PRZEWAGI",
        })
    return pd.DataFrame(rows)


def render_fokus_3f_research(remote_enabled,secret_fn):
    with st.expander("🌊 9. FOKU$ 3F — FALA / FILTR / FINAŁ (SHADOW / BADANIE)",
                     expanded=False):
        st.warning(
            "AUTO — 6 STRATEGII pozostaje nr 1 i bez zmian. FOKU$ 3F "
            "NIE oddaje głosu do AUTO ani nie otwiera PAPER/brokerowych zleceń. "
            "LONG i SHORT poniżej to HIPOTEZY badawcze M15, a nie typy.")
        st.caption(
            "Trzy potwierdzone szczyty/dołki (2 zamknięte świece po lewej "
            "i dwie po prawej) w jednej regularnej sesji NY. "
            "Poziomy w tolerancji 0,35 ATR14; przebicie 0,1 ATR; "
            "potwierdzenie EMA21 i jej kierunku. TP 1,8R, "
            "SL 0,15 ATR za dwoma ostatnimi ekstremami. "
            "Ostatnia sesyjna świeca nie jest przedłużana przez noc.")
        if remote_enabled():
            try:
                remote=RemoteCheckpoint(
                    secret_fn("FOKUS_SUPABASE_URL"),
                    secret_fn("FOKUS_SUPABASE_SECRET_KEY"))
                _,payload=remote.fetch()
                state=payload.get("fokus_3f_forward") or {}
                report=payload.get("fokus_3f_forward_report") or {}
                meta=payload.get("meta") or {}
                if state:
                    st.caption(
                        "Automatyczny SHADOW z Northflank: "+
                        str(meta.get("fokus_3f_status","BRAK STATUSU"))+
                        " | ostatnia M15: "+str(state.get("last_closed_utc","BRAK"))+
                        " | nowe sygnały: "+str(len(state.get("events") or [])))
                    if state.get("events"):
                        st.dataframe(pd.DataFrame(state["events"][-20:]),
                                     hide_index=True,use_container_width=True)
                        st.dataframe(pd.DataFrame(report.get("rank") or
                            research_scorecard(state["events"])),
                            hide_index=True,use_container_width=True)
                    else:
                        st.info("SHADOW zapisuje wyłącznie NOWE sygnały po "
                                "pierwszym uruchomieniu. Brak archiwum to "
                                "nie dowód braku formacji w przeszłości.")
                else:
                    st.info("Brak stanu FOKU$ 3F FORWARD w Supabase. "
                            "Kod GitHub musi najpierw zostać uruchomiony "
                            "na aktualnym workerze Northflank i zobaczyć nową M15.")
            except (RemoteError,ValueError,TypeError,KeyError,
                    OverflowError,OSError):
                st.warning("Nie udało się odczytać checkpointu FOKU$ 3F. "
                           "To nie potwierdza awarii skanera Northflank.")
        else:
            st.info("Automatyczny SHADOW wymaga prywatnego podglądu Supabase.")

        st.markdown("**Oddzielny replay historyczny — na żądanie**")
        uploaded=st.file_uploader(
            "Opcjonalny źródłowy CSV M15 OHLC (nie tabela gotowych wyników)",
            type=["csv"],key="fokus_3f_upload")
        clock=st.radio("Znacznik czasu załadowanego CSV",
                       ["open","close"],horizontal=True,
                       format_func=lambda x:(
                           "OPEN — czas otwarcia świecy" if x=="open"
                           else "CLOSE — czas zamknięcia świecy"),
                       key="fokus_3f_clock")
        verified=st.checkbox(
            "Potwierdzam konwencję czasu i źródło przesłanego CSV",
            key="fokus_3f_clock_verified")
        col1,col2=st.columns(2)
        cloud_clicked=col1.button("🔬 ZBADAJ ARCHIWUM CAPITAL M15",
                                   key="fokus_3f_cloud_run")
        upload_clicked=col2.button("📁 ZBADAJ PRZESŁANY CSV",
                                   key="fokus_3f_csv_run")
        if cloud_clicked or upload_clicked:
            try:
                if upload_clicked:
                    if uploaded is None or not verified:
                        raise ValueError("Dodaj źródłowy CSV i potwierdź zegar.")
                    raw=uploaded.getvalue()
                    if len(raw)>35_000_000:
                        raise ValueError("Zbyt duży plik CSV (>35 MB)")
                    frame=read_wave_m15_csv(
                        io.BytesIO(raw),timestamp_convention=clock)
                    source="UPLOADED_M15_CSV_RESEARCH"
                else:
                    if not remote_enabled():
                        raise ValueError("Brak zdalnego odczytu Supabase")
                    remote=RemoteCheckpoint(
                        secret_fn("FOKUS_SUPABASE_URL"),
                        secret_fn("FOKUS_SUPABASE_SECRET_KEY"))
                    frame=remote.fetch_candles("US500","MINUTE_15",limit=3000)
                    source="Capital.com DEMO M15 SUPABASE"
                log=run_3f_replay(frame)
                st.session_state["_fokus_3f_replay"]={
                    "source":source,"candles":len(frame),
                    "last_utc":frame.index[-1].isoformat(),
                    "log":log,
                }
            except (RemoteError,ValueError,TypeError,KeyError,OverflowError,
                    OSError,IndexError) as exc:
                st.session_state.pop("_fokus_3f_replay",None)
                st.error("FOKU$ 3F: replay niemożliwy: "+
                         type(exc).__name__+" — "+
                         (str(exc)[:180] if isinstance(exc,ValueError)
                          else "sprawdź format zamkniętych M15 i dostęp."))
        result=st.session_state.get("_fokus_3f_replay")
        if result:
            log=result["log"]
            st.caption("Źródło: "+result["source"]+
                       " | M15: "+str(result["candles"])+
                       " | ostatnia świeca UTC: "+result["last_utc"])
            if log.empty:
                st.info("0 spełnionych sygnałów 3F w dostępnym zakresie. "
                        "Nie oznacza to ani zysku, ani straty.")
            else:
                st.dataframe(pd.DataFrame(research_scorecard(log)),
                             hide_index=True,use_container_width=True)
                st.dataframe(_performance_by_period(log),
                             hide_index=True,use_container_width=True)
                st.dataframe(log.tail(100),hide_index=True,
                             use_container_width=True)
                st.download_button("⬇️ FOKU$ 3F — RAPORT ZDARZEŃ CSV",
                                   log.to_csv(index=False).encode("utf-8-sig"),
                                   file_name="FOKUS_3F_RESEARCH_EVENTS.csv",
                                   mime="text/csv",key="fokus_3f_events_download")
            st.caption(
                "70/30 to podział eksploracyjny, NIE nowy niezależny OOS. "
                "Każde wejście w replay jest odtworzone z OPEN następnej "
                "ZAMKNIĘTEJ świecy; 0,25 pkt poślizgu na stronę, "
                "spread z zamkniętych świec lub założenie 2 pkt. "
                "SL ma pierwszeństwo przed TP przy nieznanej kolejności. "
                "Brak potwierdzonej skuteczności i zerowy dostęp do handlu.")
