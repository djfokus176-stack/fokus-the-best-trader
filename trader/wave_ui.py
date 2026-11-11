"""Read-only Streamlit WAVE REVERSAL AI M15 offline audit UI.

No broker client imports, no capital API requests, no remote mutations.
Every result is explicitly exploratory; a large in-sample ranking can be
misleading due to repeated filters, correlated events and data snooping.
"""
from __future__ import annotations

import hashlib
import io

import pandas as pd
import streamlit as st

from .wave_reversal_eval import analyze_wave_m15,read_wave_m15_csv


def render_wave_reversal_research():
    with st.expander(
        "🌊 WAVE REVERSAL AI — SZCZYTY 2–5 / BOS / PRAWDOPODOBIEŃSTWA M15 "
        "(TYLKO BADANIA)",expanded=False):
        st.warning(
            "🧪 To NIE jest kolejna strategia AUTO i NIE generuje pozycji PAPER. "
            "Wynik 72/240 = 30% z obcego badania jest HIPOTEZĄ, "
            "niepotwierdzoną przewagą netto. Tu liczymy wyłącznie na realnie "
            "wgranych, zamkniętych świecach M15.")
        st.caption(
            "Wykrywanie pivotów: 2 starsze + 2 późniejsze, już ZAMKNIĘTE M15; "
            "RAW to powstanie formacji, BOS to późniejsze zamknięcie za "
            "lokalnym wsparciem/oporem. Szczyty i dołki: 2, 3, 4 i 5. "
            "DOUBLE/TRIPLE: poziomy różniące się maks. 0,25 ATR. "
            "Sesja 09:45–16:00 ET, z uwzględnieniem zmiany czasu Nowego Jorku.")
        upload=st.file_uploader(
            "CSV M15: Time,Open,High,Low,Close (+ prawdziwe Spread, "
            "Volume lub komplet BidOpen/AskOpen/BidHigh/AskHigh/...)",
            type=["csv"],key="wave_rev_m15_source",
            help="M15 z 2021–2026: wgrywaj CZAS ZAMKNIĘCIA w UTC. "
                 "Nie przekładaj ręcznie świec M1 i nie symuluj wolumenu.")
        clock=st.radio(
            "Konwencja czasu w źródłowym CSV M15 (UTC)",
            ["CLOSE — znacznik oznacza ZAMKNIĘCIE",
             "OPEN — znacznik oznacza OTWARCIE; przesuń +15 min"],
            index=0,key="wave_m15_clock",horizontal=True)
        clock_value=("open" if clock.startswith("OPEN") else "close")
        checked=st.checkbox(
            "Potwierdzam: sprawdziłem w dokumentacji/źródle, "
            "czy Time oznacza OPEN czy CLOSE i poprawnie wybrałem powyżej",
            value=False,key="wave_m15_close_clock")
        c1,c2=st.columns(2)
        with c1:
            assumed_spread=st.number_input(
                "Spread modelowany gdy brak BID/ASK i Spread (pkt)",
                min_value=0.,max_value=50.,value=1.5,step=.1,
                key="wave_m15_assumed_spread")
        with c2:
            slippage=st.number_input(
                "Poślizg na stronę (pkt)",min_value=0.,max_value=10.,
                value=.25,step=.05,key="wave_m15_slippage")
        st.caption(
            "Dla CSV bez historycznych kwotowań przy domyślnych parametrach "
            "zakładamy koszt około 2 pkt round-trip (1,5 spread + "
            "2×0,25 poślizgu). Gdy są pełne BID/ASK OHLC, wykorzystujemy "
            "je zamiast przyjmować spreado zaobserwowany. "
            "VWAP i filtr wolumenu są NIEDOSTĘPNE bez rzeczywistej "
            "kolumny Volume. Dzień giełdowy nie jest weryfikowany "
            "zewnętrznym kalendarzem świąt NYSE.")
        if st.button(
            "🌊 URUCHOM WAVE REVERSAL: RANKING RAW vs BOS / 2021–2026",
            key="wave_m15_run",use_container_width=True):
            if upload is None:
                st.error("Brak pliku M15 — nie pokazuję fikcyjnych wyników.")
            elif not checked:
                st.error("Potwierdź konwencję czasu M15 CLOSE UTC. "
                         "W przeciwnym razie powstanie lookahead.")
            else:
                try:
                    raw=upload.getvalue()
                    frame=read_wave_m15_csv(
                        io.BytesIO(raw),timestamp_convention=clock_value)
                    with st.spinner(
                        "Badanie M15: potwierdzone fale, BOS, 3 poziomy × "
                        "3 horyzonty, LONG/SHORT, lata, koszty i OOS..."):
                        rank,events,years,meta=analyze_wave_m15(
                            frame,spread_assumption=assumed_spread,
                            slippage=slippage)
                    st.session_state["_wave_reversal_results"]={
                        "file_sha256":hashlib.sha256(raw).hexdigest(),
                        "costs":(assumed_spread,slippage,clock_value),
                        "ranking":rank,"events":events,"years":years,
                        "meta":meta}
                except (ValueError,TypeError,KeyError,OverflowError) as exc:
                    st.session_state.pop("_wave_reversal_results",None)
                    st.error("Błąd testu WAVE M15: "+str(exc)[:260])
        result=st.session_state.get("_wave_reversal_results")
        if not result:
            st.info("Status: BRAK DANYCH M15 — żaden wariant nie został "
                    "zweryfikowany. Wgraj źródłowe świece, nie tylko "
                    "podsumowanie 72/240.")
            return
        fresh=(upload is not None and checked and
               result["file_sha256"]==hashlib.sha256(
                   upload.getvalue()).hexdigest() and
               result["costs"]==(assumed_spread,slippage,clock_value))
        if not fresh:
            st.warning("Zmieniono dane, spread, poślizg lub konwencję czasu. "
                       "Poprzednie wyniki ukryte; uruchom test ponownie.")
            return
        meta=result["meta"]
        st.success(
            f"Wczytano {meta['source_rows']} M15; "
            f"wykryte zdarzenia RAW + BOS: {meta['signals']}; "
            f"podział 70/30: {meta['split_utc']}. "
            f"Interpretacja czasu źródłowego: {clock_value.upper()}. "
            "To WYNIKI BADAWCZE, nie przewaga handlowa.")
        st.caption(
            "Koszty: "+("pełne BID/ASK OHLC" if meta["bidask_full"]
                      else "Spread z CSV (przybliżenie)" if meta["spread_in_file"]
                      else "stałe ZAŁOŻENIE, brak BID/ASK")+
            "; VWAP/Volume: "+("dane w CSV, niezweryfikowany dostawca"
                     if meta["volume_in_file"] else "BRAK — filtr niedostępny")+
            ". 70/30 to tylko wstępny holdout, po obejrzeniu rankingu "
            "nie jest już nieużywanym testem.")
        rank=result["ranking"]
        a,b,c,d=st.columns(4)
        with a:
            focus=st.selectbox("Liczba fal",["WSZYSTKIE",2,3,4,5],
                               key="wave_m15_count")
        with b:
            direction=st.selectbox("Kierunek",["SHORT","LONG","OBYDWA"],
                                   key="wave_m15_side")
        with c:
            confirm=st.selectbox("Potwierdzenie",["BOS","RAW","OBYDWA"],
                                 key="wave_m15_bos")
        with d:
            period=st.selectbox("Próba",["POZNIEJSZE","WCZESNIEJSZE"],
                                key="wave_m15_period")
        e,f,g,h=st.columns(4)
        with e:
            pct=st.selectbox("Próg ruchu %",[.25,.5,1.],
                             index=1,key="wave_m15_pct")
        with f:
            horizon=st.selectbox("Horyzont godzin",[1,2,4],
                                 index=1,key="wave_m15_horizon")
        with g:
            pattern=st.selectbox(
                "Formacja",["ANY","DOUBLE TOP","TRIPLE TOP",
                            "DOUBLE BOTTOM","TRIPLE BOTTOM"],
                key="wave_m15_pattern")
        with h:
            filt=st.selectbox("Filtr",["BASE","EMA","RSI","ATR",
                  "VWAP","VOLUME","EMA+RSI+ATR",
                  "EMA+RSI+ATR+VWAP+VOLUME"],key="wave_m15_filter")
        view=rank[(rank.okres==period)&(rank.target_pct==pct)&
                  (rank.horizon_h==horizon)&(rank.pattern==pattern)&
                  (rank["filter"]==filt)]
        if focus!="WSZYSTKIE":
            view=view[view.wave_count==focus]
        if direction!="OBYDWA":
            view=view[view.direction==direction]
        st.markdown("#### Prawdopodobieństwo i wynik netto — porównanie")
        columns=["direction","wave_count","pattern","confirmation",
                 "n","hits","probability_pct","wilson95_lower_pct",
                 "wilson95_upper_pct","baseline_random_side_pct",
                 "lift_pp","lower95_lift_pp","net_sum_pts",
                 "net_avg_pts","profit_factor","max_drawdown_pts","status"]
        st.dataframe(
            view.sort_values(["n","lift_pp"],ascending=[False,False])
                [columns],hide_index=True,use_container_width=True)
        st.caption(
            "Losowy punkt odniesienia = kierunek 50/50 przy tej SAMEJ godzinie; "
            "nie stanowi portfela losowych wejść. Wybrane sygnały są "
            "odstępne co najmniej o wybrany horyzont w ramach sesji. "
            "Wilson 95% i przedział lift są przybliżeniami, "
            "nie korektą na testowanie tysięcy wariantów.")
        st.warning(
            "Status weryfikacji: BRAK STATYSTYCZNIE POTWIERDZONEJ PRZEWAGI "
            "DO REALNEGO TRADINGU. Dodatni wynik z tego badania może co "
            "najwyżej wyznaczyć hipotezę na nowy, nieobserwowany okres "
            "SHADOW/FORWARD. Nie przełączam AUTO.")
        with st.expander("📅 Porównanie rok po roku i pełny ranking"):
            if result["years"].empty:
                st.info("Brak rocznych rozliczeń o kompletnym horyzoncie.")
            else:
                st.dataframe(result["years"],hide_index=True,
                             use_container_width=True)
            st.download_button(
                "⬇️ PEŁNY RANKING WAVE CSV",
                data=rank.to_csv(index=False).encode("utf-8-sig"),
                file_name="FOKUS_WAVE_REVERSAL_RANKING.csv",
                mime="text/csv",key="wave_rank_export")
            st.download_button(
                "⬇️ ROCZNE WYNIKI WAVE CSV",
                data=result["years"].to_csv(index=False).encode("utf-8-sig"),
                file_name="FOKUS_WAVE_REVERSAL_YEARS.csv",
                mime="text/csv",key="wave_annual_export")
            if not result["events"].empty:
                st.download_button(
                    "⬇️ ZDARZENIA, CECHY, PNL I HORYZONTY CSV",
                    data=result["events"].to_csv(index=False).encode("utf-8-sig"),
                    file_name="FOKUS_WAVE_REVERSAL_EVENTS.csv",
                    mime="text/csv",key="wave_events_export")
        st.caption("Wersja badawcza: "+str(meta["module"])+
                   ". Każdy wariant bez testu ma status BRAK DANYCH. "
                   "Nie sumuj wyników nakładających się formacji "
                   "jak niezależnych transakcji ani nie utożsamiaj z AUTO.")
