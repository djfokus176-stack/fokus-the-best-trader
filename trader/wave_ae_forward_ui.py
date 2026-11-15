"""Owner-only, read-only view of durable automatic A–E FORWARD paper research."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render_wave_ae_forward_status(state, report, meta):
    with st.expander(
        "📊 A–E FORWARD — AUTOMATYCZNE ROZLICZANIE NOWYCH M15",
        expanded=False):
        if not isinstance(state,dict) or not state:
            st.info("Automatyczny rejestr A–E nie został jeszcze zainicjowany. "
                    "Pierwsza nowa zamknięta M15 jedynie wyznacza punkt startu; "
                    "nie przepisujemy historii jako nowego FORWARD.")
            return
        if not isinstance(report,dict) or report.get("schema")!="wave_ae_forward_v1":
            st.warning("Brak poprawnego raportu A–E w checkpointcie.")
            return
        a,b,c=st.columns(3)
        a.metric("Nowe formacje FORWARD",report.get("events_forward",0))
        b.metric("Rozliczone warianty",report.get("closed_outcomes",0))
        c.metric("Decyzja handlowa","WAIT")
        st.caption(
            "Silnik A/B/C/D/E uruchamiany przez workera przy nowej M15. "
            "Źródło: Capital.com DEMO REST | ostatnia M15 UTC: "+
            str(report.get("last_closed_utc") or "BRAK")+
            " | status: "+str((meta or {}).get("wave_ae_status","NIEZNANY")))
        st.warning(
            "To RESEARCH/PAPER, a nie egzekucja transakcji. 5 wariantów "
            "z tej samej formacji jest ze sobą skorelowanych. "
            "Wyniki korzystają z historycznego spreadu i modelowanego "
            "poślizgu, nie pełnego BID/ASK, prowizji i rzeczywistych filli. "
            "Małe próby, wcześniejsze oglądanie parametrów i brak "
            "niezależnego OOS oznaczają WAIT; żadna strategia nie "
            "przechodzi automatycznie do AUTO.")
        if report.get("events_forward",0):
            st.markdown("**Ranking A–E według kierunku (wyniki wyłącznie rozliczone)**")
            table=pd.DataFrame(report.get("rank") or [])
            if not table.empty:
                st.dataframe(table,hide_index=True,use_container_width=True)
                st.download_button(
                    "⬇️ A–E FORWARD — ranking CSV",
                    data=table.to_csv(index=False).encode("utf-8-sig"),
                    file_name="FOKUS_WAVE_AE_FORWARD_RANKING.csv",
                    mime="text/csv",key="wave_ae_forward_rank_csv")
            records=[]
            for anchor in (state.get("events") or [])[-80:]:
                for name,variant in (anchor.get("variants") or {}).items():
                    records.append({
                        "anchor_utc":anchor.get("anchor_utc"),
                        "anchor_id":anchor.get("anchor_id"),
                        "direction":anchor.get("anchor_side"),
                        "variant":name,
                        "status":variant.get("status"),
                        "signal_utc":variant.get("signal_utc"),
                        "entry_utc":variant.get("entry_utc"),
                        "exit_utc":variant.get("exit_utc"),
                        "net_pts":variant.get("pnl_pts"),
                    })
            if records:
                with st.expander("Rozliczenia poszczególnych A–E"):
                    st.dataframe(pd.DataFrame(records),hide_index=True,
                                 use_container_width=True)
        else:
            st.info("Brak nowych trzecich szczytów/dołków od uruchomienia. "
                    "To poprawny wynik, nie awaria.")
