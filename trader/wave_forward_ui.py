"""Streamlit owner-visible FORWARD/5Y monitoring; never changes AUTO."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .wave_forward_monitor import audit_wave_forward


def render_wave_forward_comparison(state):
    st.markdown("#### 📊 FORWARD M15 kontra zamrożony ranking 5Y")
    try:
        audit=audit_wave_forward(state)
    except (ValueError,TypeError,KeyError,OverflowError,OSError) as exc:
        st.error("Nie mogę zweryfikować monitoringu WAVE FORWARD: "+str(exc)[:180])
        return
    st.caption(
        "Nowe WAVE SHADOW: "+str(audit["source_live"])+
        " | historyczny benchmark: "+str(audit["source_history"])+
        " | ostatnia M15 UTC: "+str(audit["last_closed_utc"] or "BRAK"))
    a,b,c=st.columns(3)
    a.metric("FORWARD — unikalne formacje",audit["forward_events"])
    b.metric("Dni z FORWARD (NY)",audit["forward_sessions"])
    c.metric("Zgoda na handel WAVE",audit["trade_permission"])
    st.warning(
        "Te dwie próby mają INNE źródła, definicje wyników i koszty. "
        "FORWARD SHADOW mierzy wyłącznie ruchy w horyzoncie, NIE jest "
        "wynikiem strategii A/B/C/D ani nowym zyskiem OOS. Nie wolno "
        "łączyć ich liczebności, liczyć wspólnego win rate lub "
        "pokazywać skalibrowanego prawdopodobieństwa LONG/SHORT. WAIT.")
    if audit["forward_events"]:
        st.markdown("**Obserwowane, rozłączne kierunki ruchu FORWARD (LICZBY, nie prognozy)**")
        st.caption(
            "UP tylko, DOWN tylko, BOTH (obydwa progi dotknięte) i FLAT "
            "są wzajemnie wykluczające; warunki z jednej formacji nakładają się. "
            "Unieważnione, oczekujące i błędne nie są stratami. "
            "Wiersz to jedna kombinacja kierunku, horyzontu i progu.")
        show=audit["cohorts"].rename(columns={
            "side":"Kierunek","minutes":"Horyzont (min)",
            "threshold_pct":"Próg (%)","events":"Formacje",
            "sessions":"Dni NY","resolved":"Rozliczone",
            "invalidated":"Unieważnione","pending":"Oczekujące",
            "bad":"Błędne","up_only":"Tylko UP",
            "down_only":"Tylko DOWN","both":"BOTH","flat":"FLAT"})
        st.dataframe(show,hide_index=True,use_container_width=True)
        st.download_button("⬇️ FORWARD — audyt warunków CSV",
                           data=show.to_csv(index=False).encode("utf-8-sig"),
                           file_name="FOKUS_WAVE_FORWARD_CONDITIONS.csv",
                           mime="text/csv",key="wave_forward_conditions_csv")
        if (audit["cohorts"]["bad"]>0).any():
            st.error(
                "W części zdarzeń występują nierozpoznane lub sprzeczne wyniki. "
                "Zostały wyłączone z rozliczeń; sprawdź checkpoint.")
    else:
        st.info("Brak nowych formacji FORWARD. Początkowy BACKFILL nie "
                "jest nowym testem przyszłych sygnałów.")
    st.markdown("**Osobny benchmark 2021–2026: A/B/C/D/E (późniejsze 30%, już oglądane)**")
    ref=audit["reference"].rename(columns={
        "FORMACJA":"Wariant historyczny",
        "LONG_SHORT":"Kierunek",
        "PROBY_OOS":"Próby w późniejszej próbce",
        "NETTO_OOS":"Wynik netto, pkt",
        "PF_OOS":"Profit Factor",
        "EXPECTANCY_OOS":"Expectancy, pkt",
        "STATUS":"Status badania"})
    st.dataframe(ref,hide_index=True,use_container_width=True)
    st.caption(
        "Ranking pochodzi z zapisanego wyniku badania Dukascopy; "
        "późniejszy odcinek 30% NIE jest już niezależnym dziewiczym OOS. "
        "Do bezpośredniego porównania i walidacji po kosztach trzeba "
        "uruchomić identyczną strategię A–E na nowych świecach Capital "
        "z rzeczywistym BID/ASK i osobnym rozliczeniem transakcji.")
