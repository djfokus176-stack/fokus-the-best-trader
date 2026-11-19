"""Transparent, auto-updated observed strategy ranking from Supabase archive.

This is NOT a recommendation engine. It never retunes AUTO, submits an
order, or reinterprets old OPEN/INVALIDATED as completed.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .periodic_archive_audit import LANES
from .strategy_archive_ranking import strategy_ranking

LABELS={
    "day":"DZIEŃ",
    "week":"TYDZIEŃ",
    "month":"MIESIĄC",
    "all":"CAŁE DOSTĘPNE ARCHIWUM",
}


def ranking_data_frame(summary):
    rows=[]
    for p in summary["rows"]:
        rows.append({
            "Miejsce":p["rank"],
            "Strategia":p["strategy"],
            "Zamknięte":p["count"],
            "LONG":p["long"],"SHORT":p["short"],
            "Wygrane":p["wins"],"Przegrane":p["losses"],
            "Skuteczność %":p["win_rate_pct"],
            "Netto pkt":p["net_pts"],
            "Średnio pkt":p["avg_pts"],
            "PF":p["profit_factor"],
            "Max obsunięcie pkt":p["max_drawdown_pts"],
            "TP":p["tp"],"SL":p["sl"],
            "TIMEOUT":p["timeout"],
            "Ostatnie CLOSE (PL)":p["last_closed_pl"],
            "Wiarygodność próby":p["evidence"],
        })
    return pd.DataFrame(rows)


def render_strategy_ranking(archive,selected,*,widget_scope="terminal",now=None):
    st.markdown("### 🏆 RANKING STRATEGII — DZIEŃ / TYDZIEŃ / MIESIĄC")
    st.caption(
        "Automatycznie z zamkniętych transakcji archiwum Supabase, "
        "aktualizacja po kolejnych skanach Northflank. "
        "Rozdzielone AUTO PAPER v3, RAW i MOMENTUM; testów ręcznych "
        "nie uwzględniam. Sygnałów WAIT/PENDING/OPEN nie liczę jako wyników."
    )
    lane=st.selectbox(
        "Który system oceniasz?",
        options=list(LANES),index=0,
        key="fokus_strategy_ranking_lane_v1_"+widget_scope)
    direction=st.selectbox(
        "Kierunek analizowanych pozycji",
        options=["BOTH","LONG","SHORT"],
        format_func=lambda x:{"BOTH":"LONG + SHORT","LONG":"Tylko LONG",
                              "SHORT":"Tylko SHORT"}[x],
        key="fokus_strategy_ranking_side_v1_"+widget_scope)
    if lane=="RAW M1 TEST":
        st.caption("RAW z wieloma zgodnymi sygnałami występuje jako "
                   "jedna KOMBINACJA, żeby tego samego zysku/straty "
                   "nie przypisywać kilku strategiom.")

    day=selected
    reports={
        kind:strategy_ranking(archive,lane,kind,
                              reference=day,now=now,direction=direction)
        for kind in LABELS
    }
    # A quick visible comparison without expanding other report sections.
    cols=st.columns(3)
    for col,kind in zip(cols,("day","week","month")):
        current=reports[kind]
        top=current["rows"][0] if current["rows"] else None
        with col:
            st.markdown("**"+LABELS[kind]+"**")
            if top:
                st.metric("Najwyższy wynik netto",
                          f'{top["net_pts"]:+.2f} pkt')
                st.caption(
                    top["strategy"]+" • "+str(top["count"])+" zamknięć • "+
                    top["evidence"]
                )
            else:
                st.caption("BRAK ZAMKNIĘTYCH TRANSAKCJI W OKRESIE")

    tabs=st.tabs(["📅 DZIENNIE","📆 TYGODNIOWO",
                  "🗓️ MIESIĘCZNIE","📚 CAŁE ARCHIWUM"])
    for tab,(kind,summary) in zip(tabs,reports.items()):
        with tab:
            st.caption(
                "Okres od (UTC): "+str(summary["start_utc"] or
                                     "pierwszy zachowany wpis")+
                " • do: "+summary["end_utc"]+
                " • liczba rozliczeń: "+str(summary["total_closed"])+
                " • wynik netto w wybranym rejestrze: "+
                f'{summary["total_net_pts"]:+.2f} pkt'
            )
            df=ranking_data_frame(summary)
            if df.empty:
                st.info("Brak rozliczonych transakcji wybranego systemu "
                        "i kierunku w tym okresie. Nie przypisuję "
                        "zerowej skuteczności bez danych.")
                continue
            st.dataframe(df,hide_index=True,use_container_width=True)
            st.download_button(
                "📥 Pobierz ranking "+LABELS[kind]+" (CSV)",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                mime="text/csv",
                file_name="FOKUS_RANKING_"+lane.replace(" ","_")+"_"+kind+
                          "_"+selected.isoformat()+".csv",
                key="fokus_strategy_rank_csv_"+kind+"_"+widget_scope)
            if not any(r["sample_sufficient"] for r in summary["rows"]):
                st.warning("Wszystkie strategie mają mniej niż 30 "
                           "zamkniętych transakcji w tym okresie. "
                           "Kolejność jest WSTĘPNA, a nie dowodem "
                           "najlepszej strategii.")
            else:
                st.caption("Miejsce wynika wyłącznie z obserwowanego "
                           "netto w punktach. 30+ transakcji nadal "
                           "nie oznacza potwierdzonej przewagi "
                           "ani wyników na rachunku rzeczywistym.")
