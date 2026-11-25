"""Owner-only read-only event journal for signed PAPER v3 checkpoint."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .verified_signal_journal import verified_signal_rows


def render_signal_journal(payload,*,attempts=None):
    st.markdown("##### 🕒 DZIENNIK SYGNAŁÓW LONG/SHORT — KIEDY BOT NAPRAWDĘ JE ZAPISAŁ?")
    st.caption(
        "Zdarzenia OPEN/CLOSE z archiwum workera Northflank, nie z "
        "hipotetycznych OBSERWUJ ani PENDING. Modelowana godzina wejścia "
        "to nie godzina podania sygnału! Dopiero 'Sygnał zapisany przez "
        "worker' pokazuje udokumentowany moment jego powstania. "
        "To SYMULACJE, nie zlecenia u brokera."
    )
    records=verified_signal_rows(payload,limit=25)
    if not records:
        st.warning("W aktualnie odczytanym checkpoint nie ma zweryfikowanych "
                   "zdarzeń otwarcia/zamknięcia AUTO PAPER v3. "
                   "Nie wpisuję umownych godzin ani nie odtwarzam historii głosu.")
        return
    attempts_by_id={
        a["event_id"]:a for a in (attempts or []) if isinstance(a,dict)
        and isinstance(a.get("event_id"),str)
    }
    rows=[]
    for signal in records:
        attempt=attempts_by_id.get(signal["event_id"])
        audio_status=(
            "PRÓBA "+str(attempt.get("mode"))+" "+str(attempt.get("attempt_pl"))
            +" — odsłuch NIEPOTWIERDZONY"
            if attempt else "BRAK UDOKUMENTOWANEJ PRÓBY W TEJ SESJI"
        )
        rows.append({
            "Zdarzenie":signal["label"],
            "Strategia":signal["method"],
            "Modelowe wejście (PL)":signal["modeled_open_pl"],
            "Potwierdzenie świecy (PL)":signal["confirmed_pl"],
            "Sygnał workera (PL)":signal["worker_event_pl"],
            "Próba dźwięku (ta sesja)":audio_status,
            "Wynik netto pkt":signal["net_pts"],
            "ID":signal["trade_id"][:14],
        })
    st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
    st.caption(
        "Godziny są w strefie Europe/Warsaw. Brak próby w tej sesji nie "
        "dowodzi, że alert nie pojawił się w innej przeglądarce lub sesji. "
        "Nawet zarejestrowana próba VOICE nie oznacza potwierdzonego "
        "odtworzenia — Chrome może blokować autoplay. "
        "Powiadomienia dźwiękowe działają tylko z otwartą stroną."
    )
    with st.expander("📥 Eksportuj dziennik sygnałów",expanded=False):
        st.download_button(
            "Pobierz CSV — godziny OPEN i zdarzeń workera",
            data=pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
            file_name="FOKUS_SYGNALY_PAPER_v3.csv",
            mime="text/csv",
            key="fokus_paper_event_journal_download_v1",
        )
