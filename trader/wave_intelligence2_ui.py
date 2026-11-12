"""WAVE INTELLIGENCE 2.0 research panel. Never edits AUTO/worker/Supabase."""
from __future__ import annotations

import hashlib
import io

import pandas as pd
import streamlit as st

from .wave_reversal_eval import read_wave_m15_csv
from .wave_intelligence2 import run_wave_abcd, M15_UNSUPPORTED_MIN
from .wave_intelligence2_stats import (
    wave_excursion_audit, feature_audit, hour_ranking, timeframe_coverage,
    same_entries_exit_grid, wave_pattern_ranking,
)


def render_wave_intelligence2():
    with st.expander("🌊 WAVE INTELLIGENCE 2.0 — PORÓWNANIE A/B/C/D/E (M15, BADANIA)",
                     expanded=False):
        st.warning(
            "Ten panel nie otwiera zleceń. AUTO nadal ma 6 strategii. "
            "WAVE daje wyłącznie hipotetyczne zdarzenia badawcze, nie "
            "skalibrowane prognozy LONG/SHORT. Bez nowej walidacji: WAIT.")
        st.caption(
            "A = formacja po potwierdzeniu 3. szczytu/dołka, "
            "B = późniejsze zamknięcie za wsparciem/oporem, "
            "C = B + zamknięty retest poziomu, "
            "D = dwa zamknięcia za zewnętrznym maksimum/minimum w "
            "PRZECIWNYM kierunku, E = WAIT. "
            "Każdy kandydat z jednego trzeciego swingu tworzy tę samą "
            "kohortę; B/C/D mogą nie zaistnieć i wtedy nie tworzymy trade'u.")
        f=st.file_uploader(
            "Wgraj źródłowe M15 OHLC 2021–2026 (Time,Open,High,Low,Close; "
            "opcjonalnie Spread, Volume i pełne 8 kolumn Bid/Ask OHLC)",
            type=["csv"],key="wave2_csv")
        existing=st.session_state.get("wave_rev_m15_source")
        file=f or existing
        clock=st.radio(
            "Oryginalny znacznik czasu pliku (UTC)",
            ["open","close"],format_func=lambda s:(
               "OPEN — jak standardowe M15 Dukascopy" if s=="open"
               else "CLOSE — świeca opisana czasem zamknięcia"),
            horizontal=True,key="wave2_clock")
        confirm=st.checkbox(
            "Potwierdzam sprawdzoną konwencję czasu i źródło instrumentu "
            "(CFD US500 to nie automatycznie ES futures)",
            key="wave2_clock_confirm")
        a,b,c,d=st.columns(4)
        with a:
            spread=st.number_input("Zastępczy spread (pkt)",
                min_value=0.,max_value=40.,value=2.,step=.25,key="wave2_spread")
        with b:
            slip=st.number_input("Poślizg na stronę (pkt)",
                min_value=0.,max_value=10.,value=.25,step=.05,key="wave2_slip")
        with c:
            rr=st.selectbox("Test bazowy TP w R",[1.,1.5,2.,3.],index=1,
                            key="wave2_rr")
        with d:
            hold=st.selectbox("Maksymalny czas (M15)",[30,45,60,120],
                             index=3,key="wave2_hold")
        st.caption(
            "M15 NIE pozwala dokładnie przetestować zamknięcia po "
            "10 lub 20 minutach — te czasy będą BRAK DANYCH. "
            "Brak BID/ASK i brak prowizji brokera oznacza modelowane, "
            "niepotwierdzone koszty. SL ma pierwszeństwo przy równoczesnym "
            "dotknięciu SL/TP. 70/30 jest tylko wstępną oceną OOS.")
        full_grid=st.checkbox(
            "Porównaj także pełną siatkę 4R × 6 czasów na tych samych wejściach",
            value=False,key="wave2_grid")
        if st.button("🔬 ZBADAJ TRZECIE SZCZYTY I DOŁKI — A/B/C/D/E",
                     key="wave2_run",use_container_width=True):
            if not file:
                st.error("Nie ma surowych świec M15. Plik z 1000 gotowych "
                         "zdarzeń nie wystarcza do porównania A/B/C/D.")
            elif not confirm:
                st.error("Potwierdź czas OPEN/CLOSE w źródłowym CSV.")
            else:
                try:
                    raw=file.getvalue()
                    history=read_wave_m15_csv(
                        io.BytesIO(raw),timestamp_convention=clock)
                    with st.spinner("Badanie as-of M15, zamrożone wejścia i koszty..."):
                        summary,trades,meta=run_wave_abcd(
                            history,spread=spread,slippage=slip,rr=rr,
                            hold_minutes=hold)
                        patterns=wave_pattern_ranking(summary)
                        prob,prob_detail=wave_excursion_audit(history,trades)
                        features=feature_audit(trades)
                        hours=hour_ranking(trades)
                        grid,grid_trades=(same_entries_exit_grid(
                            history,trades,split_cutoff=meta["oos_cutoff"],
                            spread=spread,slippage=slip) if full_grid
                            else (pd.DataFrame(),pd.DataFrame()))
                    st.session_state["wave2_results"]={
                        "sha":hashlib.sha256(raw).hexdigest(),
                        "params":(clock,spread,slip,rr,hold,full_grid),
                        "meta":meta,"ranking":patterns,"summary":summary,
                        "trades":trades,"prob":prob,"prob_detail":prob_detail,
                        "features":features,"hours":hours,"grid":grid,
                        "grid_trades":grid_trades}
                except (ValueError,TypeError,KeyError,OverflowError) as exc:
                    st.session_state.pop("wave2_results",None)
                    st.error("Test WAVE 2.0 zatrzymany: "+str(exc)[:250])
        result=st.session_state.get("wave2_results")
        if not result:
            st.info("STATUS: WAIT. Nie ma jeszcze pełnego raportu A–E "
                    "z pięcioletnich surowych świec M15.")
            return
        valid=(file is not None and confirm and
               hashlib.sha256(file.getvalue()).hexdigest()==result["sha"] and
               (clock,spread,slip,rr,hold,full_grid)==result["params"])
        if not valid:
            st.warning("Wymieniono plik lub parametry. Ukryłem stare wyniki — "
                       "uruchom porównanie ponownie, żeby nie mieszać prób.")
            return
        meta=result["meta"]
        st.info(
            f"Wykryto {meta['anchors']} niezależnych okazji trzeciego swingu "
            f"na {meta['total_candles']} M15. Okresy 70/30 rozdziela: "
            f"{meta.get('oos_cutoff','—')}. "
            "Nie wykryto potwierdzonej przewagi; status AUTO: NIEZMIENIONY.")
        st.markdown("#### 🏆 WAVE PATTERN RANKING — wynik po kosztach")
        st.dataframe(result["ranking"],hide_index=True,use_container_width=True)
        st.caption("Wszystkie warianty mają status WAIT/BRAK DANYCH do czasu "
                   "weryfikacji na naprawdę nowych danych. E_WAIT nigdy "
                   "nie jest sztucznie liczone jako zyskowna transakcja.")
        st.markdown("#### 📊 LONG, SHORT, OBA RUCHY i KONSOLIDACJA")
        st.dataframe(result["prob"],hide_index=True,use_container_width=True)
        st.caption("UP i DOWN mogą zajść w tym samym horyzoncie; BOTH nie jest "
                   "błędem. FLAT oznacza, że ani jeden próg nie został dotknięty. "
                   "Zdarzenia bez pełnych świec są pomijane, nie przegrane.")
        with st.expander("🔬 Dlaczego niektóre fale działały? — cechy i godziny"):
            st.dataframe(result["features"],hide_index=True,use_container_width=True)
            st.dataframe(result["hours"],hide_index=True,use_container_width=True)
        with st.expander("📅 Lata, dane wejściowe i pełne dzienniki"):
            yearly=result["summary"][result["summary"].year.notna()]
            st.dataframe(yearly,hide_index=True,use_container_width=True)
            st.dataframe(result["trades"],hide_index=True,use_container_width=True)
            st.dataframe(timeframe_coverage(),hide_index=True,use_container_width=True)
        if full_grid:
            st.markdown("#### 🧪 Ta sama grupa wejść — 1R/1,5R/2R/3R i 6 czasów")
            st.dataframe(result["grid"],hide_index=True,use_container_width=True)
            st.caption("10 i 20 minut: BRAK DANYCH M15. Wyniki innych kombinacji "
                       "nie są automatycznie promowane do AUTO.")
        for label,key,filename in (
            ("Ranking A–E","ranking","FOKUS_WAVE2_PATTERN_RANKING.csv"),
            ("Dziennik sygnałów","trades","FOKUS_WAVE2_TRADE_AUDIT.csv"),
            ("Prawdopodobieństwa","prob","FOKUS_WAVE2_EXCURSION.csv"),
            ("Analiza cech","features","FOKUS_WAVE2_FEATURES.csv"),
            ("Ranking godzin","hours","FOKUS_WAVE2_HOURS.csv"),
            ("Warianty TP/czas","grid","FOKUS_WAVE2_EXIT_GRID.csv")):
            obj=result[key]
            if obj is not None and not obj.empty:
                st.download_button("⬇️ "+label,
                    data=obj.to_csv(index=False).encode("utf-8-sig"),
                    mime="text/csv",file_name=filename,
                    key="wave2_download_"+key)
        st.warning("Bieżący status: WAIT (brak walidacji forward i kalibracji). "
                   "To raport OFFLINE, nie skaner LIVE. Automatyczna "
                   "archiwizacja każdej świecy, ranking M1/M5/H1 i "
                   "monitoring na Northflank wymagają osobnego wdrożenia "
                   "po walidacji serwera i źródeł danych.")
