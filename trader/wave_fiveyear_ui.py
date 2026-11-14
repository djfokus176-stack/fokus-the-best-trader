"""WAVE five-year verified frozen ranking in the Streamlit REPORTS tab.

Everything here is explicitly historical, read-only and independent of
AUTO/PAPER/Northflank. The bundled 10-row ranking does not need CSV upload;
full year/hour/feature tables become visible after uploading the authentic
GitHub Actions research ZIP, checked against its real source SHA256.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from .wave_fiveyear_report import (
    REFERENCE_ANCHORS, REFERENCE_BARS, REFERENCE_CUTOFF,
    REFERENCE_RUN_ID, load_reference_ranking, load_wave_fiveyear_bundle,
)


def render_wave_fiveyear_report():
    with st.expander(
        "🏆 WAVE 2021–2026 — PRAWDZIWY RANKING 5 LAT / LONG / SHORT / OOS",
        expanded=False):
        st.caption(
            "Archiwalny, zamrożony wynik GitHub Actions #43575844127 "
            "(Dukascopy USA500.IDX/USD CFD M15, rzeczywiste BID/ASK OHLC, "
            "2021-11–2026-11). Model: 1,5×ATR SL, TP 1,5R, "
            "120 min, poślizg 0,25 pkt/stronę, bez niezweryfikowanej prowizji. "
            "To NIE są transakcje obecnego Capital.com PAPER.")
        st.warning(
            "NIE POTWIERDZONO PRZEWAGI. Ujemny wynik wszystkich rozliczonych "
            "formacji w późniejszej próbce. Nie dopuszczam żadnej do AUTO. "
            "Późniejsze 30% NIE jest już dziewiczym testem forward, "
            "ponieważ obejrzeliśmy jego wyniki.")
        a,b,c=st.columns(3)
        a.metric("Zbadane świece M15",f"{REFERENCE_BARS:,}".replace(","," "))
        b.metric("Kandydaci 3. fali",f"{REFERENCE_ANCHORS:,}".replace(","," "))
        c.metric("Odcinek OOS od",REFERENCE_CUTOFF[:10])
        try:
            ranking=load_reference_ranking()
        except (OSError,ValueError) as exc:
            st.error("Nie można załadować opublikowanego rankingu: "+str(exc)[:180])
            return
        r1,r2=st.columns(2)
        with r1:
            selected=st.selectbox(
                "Kierunek formacji",["LONG i SHORT","LONG","SHORT"],
                key="wave5y_direction")
        with r2:
            min_trades=st.selectbox(
                "Minimum rozliczeń w późniejszym okresie",[0,5,20,50],
                key="wave5y_min_oos")
        view=ranking.copy()
        if selected!="LONG i SHORT":
            view=view[view.LONG_SHORT==selected]
        if min_trades:
            view=view[view.PROBY_OOS>=min_trades]
        st.markdown("**Historyczny WAVE PATTERN RANKING — po modelowanych kosztach**")
        st.dataframe(view.sort_values(["PROBY_OOS","FORMACJA"],
                         ascending=[False,True]),
                     hide_index=True,use_container_width=True)
        st.caption(
            "TRAIN i OOS liczone oddzielnie. E_WAIT oznacza brak "
            "transakcji i nie dostaje fikcyjnego zysku. "
            "Nawet dodatni wynik małej próbki nie daje statusu ZWERYFIKOWANA.")
        st.download_button(
            "⬇️ POBIERZ RANKING 5 LAT CSV",
            data=ranking.to_csv(index=False).encode("utf-8-sig"),
            file_name="FOKUS_WAVE5Y_ZWERYFIKOWANE_WYNIKI_BADANIA.csv",
            mime="text/csv",key="wave5y_builtin_rank_export")
        st.markdown("**Dodatkowe tabele — jeśli masz oryginalny plik ZIP z GitHub Actions**")
        st.caption(
            "Wgraj artefakt FOKUS-WAVE-M15-2021-2026-BID-ASK-RESEARCH.zip. "
            "Sprawdzę SHA256 oryginalnych świec i zgodność z manifestem; "
            "prześlemy go tylko do pamięci tej sesji Streamlit, "
            "bez modyfikacji bazy.")
        archive=st.file_uploader(
            "📦 Oryginalny ZIP badania WAVE 5 lat",
            type=["zip"],key="wave5y_original_bundle")
        if archive is None:
            st.info("Ranking 10 formacji jest dostępny od razu. "
                    "Pełny podział na lata, godziny, filtry i warianty wyjścia "
                    "wymaga wgrania źródłowego ZIP.")
            return
        blob=archive.getvalue()
        digest=hashlib.sha256(blob).hexdigest()
        cached=st.session_state.get("_wave5y_validated_zip")
        if not isinstance(cached,dict) or cached.get("zip_sha256")!=digest:
            try:
                results=load_wave_fiveyear_bundle(blob)
                results["zip_sha256"]=digest
                st.session_state["_wave5y_validated_zip"]=results
                cached=results
            except (ValueError,KeyError,TypeError,OverflowError,OSError,
                    pd.errors.ParserError) as exc:
                st.session_state.pop("_wave5y_validated_zip",None)
                st.error("Odrzucono niezweryfikowany ZIP: "+str(exc)[:250])
                return
        st.success(
            "Sprawdzono oryginalne 114 121 świec, SHA256, manifest i "
            "10 wyników formacji; wszystkie zgodne z badaniem #"+
            str(REFERENCE_RUN_ID)+".")
        qc=cached["quality"]
        st.caption(
            f"BID/ASK: wadliwe lub wykluczone świece "
            f"{qc.get('crossed_rows',0)} / "
            f"{qc.get('quarantined_rows',0)}. "
            "Kontrola danych nie usuwa ryzyka błędu modelu ani overfittingu.")
        details=cached["tables"]
        for heading,key,name in (
            ("📅 Wynik każdej formacji rok po roku","years",
             "WAVE_5Y_YEARS.csv"),
            ("⏰ Ranking godzin sesji Nowy Jork","hours",
             "WAVE_5Y_HOURS.csv"),
            ("↗️↘️ Prawdopodobieństwo UP / DOWN / BOTH / FLAT","probabilities",
             "WAVE_5Y_PROBABILITIES.csv"),
            ("🔎 Cechy poprzedzające zwroty ceny","features",
             "WAVE_5Y_FEATURES.csv"),
            ("🧪 Alternatywne TP i czasy wyjścia","exit_grid",
             "WAVE_5Y_EXIT_GRID.csv")):
            table=details.get(key)
            if table is None or table.empty:
                continue
            with st.expander(heading,expanded=False):
                st.dataframe(table,hide_index=True,use_container_width=True)
                st.download_button(
                    "⬇️ "+name,data=table.to_csv(index=False).encode("utf-8-sig"),
                    file_name=name,mime="text/csv",
                    key="wave5y_full_"+key)
        st.caption(
            "To zamrożony raport OFFLINE z GitHub; nie aktualizuje się "
            "sam po każdej świecy i nie jest decyzją LONG/SHORT. "
            "Status tradingowy WAVE pozostaje WAIT.")
