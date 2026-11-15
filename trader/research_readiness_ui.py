"""Read-only research data health display inside owner-only REPORTS."""
from __future__ import annotations

import streamlit as st

from .research_readiness import assess_research_readiness


def render_research_readiness(meta, wave_state, backfill_state):
    with st.expander("🩺 STAN DANYCH WAVE — checkpoint / M15 / backfill",
                     expanded=False):
        health = assess_research_readiness(meta, wave_state, backfill_state)
        st.caption(
            "Ten raport porównuje zapisane znaczniki czasu z zegarem serwera. "
            "NIE dowodzi kompletności danych brokera ani przewagi tradingowej. "
            "Kontrola M15 odnosi się do sesji kasowej Nowego Jorku "
            "09:45–16:00 ET używanej w badaniu WAVE, NIE do pełnych godzin "
            "handlu CFD Capital.com."
        )
        st.markdown("**Checkpoint workera**: "+health["checkpoint_status"])
        st.caption(
            "Ostatni checkpoint UTC: "+
            str(health["last_checkpoint_utc"] or "BRAK")+
            " | Wiek w minutach: "+
            (str(health["checkpoint_minutes"])
             if health["checkpoint_minutes"] is not None else "BRAK"))
        st.markdown("**Ostatnia świeca WAVE M15**: "+health["wave_status"])
        st.caption(
            "Ostatnia zapisana M15 UTC: "+
            str(health["last_m15_utc"] or "BRAK")+
            " | Wiek w minutach: "+
            (str(health["wave_minutes"])
             if health["wave_minutes"] is not None else "BRAK"))
        st.markdown("**Backfill**: "+health["backfill_status"])
        st.caption("Ostatnia próba UTC: "+
                   str(health["backfill_attempt_utc"] or "BRAK"))
        st.warning(
            "WAVE nadal WAIT. Świeży checkpoint nie dowodzi, że wszystkie "
            "świece M1/M5/M15/H1 są kompletne; naprawione rekordy wymagają "
            "osobnego audytu i potwierdzenia Capital.com. Stan FORWARD "
            "nie jest automatycznym sygnałem LONG ani SHORT.")
