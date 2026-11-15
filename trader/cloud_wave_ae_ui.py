"""Owner-triggered Capital DEMO A–E replay from Supabase, research only."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .remote_checkpoint import RemoteCheckpoint, RemoteError
from .cloud_wave_ae_replay import research_capital_ae


def render_cloud_wave_ae_replay(remote_enabled,secret_fn):
    with st.expander(
        "🧪 NOWE M15 CAPITAL DEMO — IDENTYCZNY SILNIK A–E (BADANIE)",
        expanded=False):
        st.warning(
            "WAVE A–E jest WYŁĄCZNIE badaniem, nie strategią AUTO. "
            "Nowe świece pochodzą z Capital.com DEMO, a pięcioletnie badanie "
            "z Dukascopy. Nie łączymy wyników ani nie ogłaszamy przewagi.")
        st.caption(
            "Po kliknięciu odczytuję do 3000 ostatnich zamkniętych M15 "
            "z Supabase i uruchamiam aktualny silnik A/B/C/D/E. "
            "W modelu wykonania używany jest zapisany spread ze "
            "wcześniejszej zamkniętej świecy + symulowany poślizg "
            "0,25 pkt na stronę. To NIE jest historyczny pełny BID/ASK, "
            "prawdziwe fill'e ani kompletny koszt prowizji.")
        if not remote_enabled():
            st.info("Aby zobaczyć replay, potrzebny jest prywatny "
                    "podgląd Supabase w Streamlit Secrets.")
            return
        if st.button("🔬 URUCHOM BADANIE A–E NA CAPITAL DEMO M15",
                     key="fokus_capital_ae_run",use_container_width=True):
            try:
                remote=RemoteCheckpoint(
                    secret_fn("FOKUS_SUPABASE_URL"),
                    secret_fn("FOKUS_SUPABASE_SECRET_KEY"))
                frame=remote.fetch_candles("US500","MINUTE_15",limit=3000)
                st.session_state["_fokus_cloud_ae_replay"]=research_capital_ae(frame)
            except (RemoteError,ValueError,TypeError,KeyError,OverflowError,
                    OSError) as exc:
                st.session_state.pop("_fokus_cloud_ae_replay",None)
                st.error("Nie można rozliczyć A–E: "+type(exc).__name__+
                         ". Sprawdź kompletność świec M15 i prawa odczytu Supabase.")
        result=st.session_state.get("_fokus_cloud_ae_replay")
        if not result:
            return
        meta=result["meta"]
        a,b,c=st.columns(3)
        a.metric("Zbadane M15",meta["stored_candles"])
        b.metric("Kandydaci 3. fali",meta["anchors"])
        c.metric("Decyzja WAVE",meta["trade_permission"])
        st.caption("Dane M15 UTC: "+meta["first_close_utc"]+
                   " → "+meta["last_close_utc"])
        st.warning(
            "Podział 70/30 służy jedynie orientacyjnemu testowi na "
            "KRÓTKIM archiwum Capital. Ta późniejsza część NIE jest nowym "
            "niezależnym OOS. Każda z opcji A–D ma inne momenty wejścia; "
            "nie traktuj wielu wariantów tego samego szczytu jako "
            "niezależnych transakcji. WAIT.")
        summary=result["summary"]
        cols=("period","anchor_side","variant","eligible_anchors",
              "triggered","closed","win_pct","net_pts",
              "profit_factor","expectancy_pts","max_drawdown_pts","status")
        safe=summary.loc[:,[c for c in cols if c in summary.columns]].copy()
        st.markdown("**Wyniki A–E według tego samego silnika badawczego**")
        st.dataframe(safe,hide_index=True,use_container_width=True)
        st.download_button(
            "⬇️ CAPITAL M15 A–E — podsumowanie CSV",
            data=safe.to_csv(index=False).encode("utf-8-sig"),
            file_name="FOKUS_CAPITAL_M15_AE_RESEARCH.csv",
            mime="text/csv",key="fokus_cap_ae_csv")
        st.caption(
            "Przy braku rozliczonych transakcji wynik netto pozostaje "
            "pusty, a nie zerowy. Nie dopuszczamy żadnej wersji do AUTO "
            "bez niezależnych przyszłych obserwacji i wiarygodnych kosztów.")
