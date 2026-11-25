"""Owner-triggered cloud OHLC audit UI; SELECT only, no worker writes."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .cloud_gap_audit import (STEP_MINUTES, REVIEW,
                              audit_closed_candle_gaps, summarize_gap_audit)
from .remote_checkpoint import RemoteCheckpoint, RemoteError


def render_cloud_gap_audit(remote_enabled, secret_fn):
    with st.expander("🔍 JAKOŚĆ ARCHIWUM — LUKI M1/M5/M15/H1 (READ-ONLY)",
                     expanded=False):
        st.caption(
            "Audyt wyłącznie na żądanie właściciela. Czyta do 5000 najnowszych "
            "zamkniętych świec na interwał z Supabase; NIE jest to pełne "
            "archiwum ani potwierdzenie kalendarza handlu Capital.com. "
            "Nie zapisuje, nie uzupełnia ani nie zmienia cen czy AUTO/PAPER."
        )
        if not remote_enabled():
            st.info("Włącz serwerowy podgląd Supabase w Streamlit Secrets. "
                    "Kluczy nie podawaj w czacie ani w przeglądarce.")
            return
        if st.button("🔎 SPRAWDŹ LUKI W ZAPISANYCH ŚWIECACH",
                     key="fokus_archive_gap_check"):
            try:
                remote=RemoteCheckpoint(
                    secret_fn("FOKUS_SUPABASE_URL"),
                    secret_fn("FOKUS_SUPABASE_SECRET_KEY"))
                summary=[]
                all_gaps=[]
                for tf in STEP_MINUTES:
                    frame=remote.fetch_candles("US500",tf,limit=5000)
                    gaps=audit_closed_candle_gaps(frame,tf)
                    summary.append(summarize_gap_audit(
                        gaps,timeframe=tf,candles=len(frame),
                        first_utc=frame.index[0] if len(frame) else None,
                        last_utc=frame.index[-1] if len(frame) else None))
                    if not gaps.empty:
                        all_gaps.append(gaps)
                columns=["timeframe","previous_utc","next_utc",
                         "gap_minutes","unobserved_slots","classification"]
                st.session_state["_fokus_gap_audit_view"]={
                    "summary":pd.DataFrame(summary),
                    "gaps":(pd.concat(all_gaps,ignore_index=True)
                            if all_gaps else pd.DataFrame(columns=columns)),
                }
            except (RemoteError,ValueError,TypeError,OverflowError,
                    KeyError,OSError) as exc:
                st.session_state.pop("_fokus_gap_audit_view",None)
                st.error("Audyt tylko do odczytu nie powiódł się: "+
                         type(exc).__name__+
                         ". Sprawdź łączność i uprawnienia Supabase.")
        result=st.session_state.get("_fokus_gap_audit_view")
        if not result:
            return
        st.markdown("**Pokrycie badanej próbki — nie całej bazy**")
        st.dataframe(result["summary"],hide_index=True,width="stretch")
        st.warning(
            "WEEKEND_OVERLAP oznacza tylko przerwę obejmującą weekend; "
            "DAILY_BREAK_CANDIDATE to hipoteza przerwy około 22:00 UTC. "
            "INTRADAY_REVIEW wymaga porównania z oryginalnymi świecami "
            "Capital.com. Brak znacznika NIE oznacza automatycznie utraconej świecy."
        )
        show_all=st.checkbox("Pokaż również kandydatów przerw weekendowych "
                             "i technicznych",value=False,
                             key="fokus_gap_show_all")
        table=result["gaps"] if show_all else result["gaps"].loc[
            result["gaps"]["classification"]==REVIEW]
        st.dataframe(table,hide_index=True,width="stretch")
        st.download_button(
            "⬇️ EKSPORT AUDYTU LUK CSV",
            data=result["gaps"].to_csv(index=False).encode("utf-8-sig"),
            file_name="FOKUS_CLOUD_OHLC_GAP_AUDIT.csv",
            mime="text/csv",key="fokus_gap_csv")
