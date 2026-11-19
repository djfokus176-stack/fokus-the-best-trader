"""Simple owner view of the automatic virtual trading ledger.

No broker API calls and no writes; the worker remains the sole author of
real OHLC-driven simulated OPEN/CLOSE transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from .auto_sim_journal import auto_sim_journal, _utc


def render_auto_sim_journal(payload):
    st.markdown("#### 🤖 BOT HANDLUJE AUTOMATYCZNIE — NA NIBY")
    st.caption(
        "Bot sam wybiera LONG lub SHORT, symuluje wejście, pilnuje SL/TP "
        "i zamyka pozycję albo po upływie limitu czasu. "
        "Wszystko zapisuje w archiwum. Bez wpłat, kwot i zleceń brokera. "
        "Techniczna nazwa tego trybu w silniku to PAPER — "
        "nie jest to żaden dodatkowy rachunek."
    )
    data=auto_sim_journal(payload)
    if not data["known"]:
        st.warning("Brak potwierdzonego dziennika automatycznych pozycji "
                   "w checkpointcie. Nie pokazuję fikcyjnych wejść.")
        return
    meta=payload.get("meta") or {}
    last=_utc(meta.get("last_scan_utc"))
    age=(datetime.now(timezone.utc)-last).total_seconds() if last else None
    if age is None or age<0 or age>600:
        st.warning("Ostatni skan workera nie jest świeży. "
                   "Poniżej widać zapisane archiwum, nie dowód bieżącej pracy bota.")
    a,b,c,d=st.columns(4)
    a.metric("Bot otworzył",data["opened"])
    b.metric("Bot zamknął",data["closed"])
    c.metric("Otwarte teraz",int(data["active"] is not None))
    d.metric("Bilans netto",f'{data["net_pts"]:+.2f} pkt')
    active=data["active"]
    if active is not None:
        st.success(
            f'🟢 OTWARTA {active["Kierunek"]} | '
            f'Strategia: {active["Strategia"]} | '
            f'Potwierdzone wejście: {active["Otwarcie (Polska)"]} | '
            f'Cena wejścia {active["Wejście (pkt)"]} | '
            f'SL {active["SL (pkt)"]} | TP {active["TP (pkt)"]}.'
        )
    else:
        st.info("⚪ Bot obecnie NIE MA OTWARTEJ pozycji. "
                "Czeka na zatwierdzony układ. WAIT nie jest awarią.")
    pending=data["pending"]
    if pending is not None:
        st.caption(f'⏳ Przygotowany {pending["Kierunek"]} '
                   f'({pending["Strategia"]}) — jeszcze NIE OTWARTY. '
                   "Otworzy się w symulacji dopiero po spełnieniu zasad "
                   "następnej zamkniętej świecy.")
    latest=data["latest_closed"]
    if latest is not None:
        outcome=latest["Status"].replace("ZAMKNIĘTA • ","")
        st.markdown(
            f'**Ostatnie zamknięcie:** {latest["Kierunek"]} — {outcome}, '
            f'{latest["Zamknięcie (Polska)"]} | '
            f'wynik **{latest["Wynik (pkt)"]:+.2f} pkt**.'
        )
    st.markdown("##### 📒 ARCHIWUM — CO BOT OTWORZYŁ I KIEDY ZAMKNĄŁ")
    displayed=([active] if active else []) + ([pending] if pending else []) + data["rows"]
    if displayed:
        fields=("Kierunek","Strategia","Status","Otwarcie (Polska)",
                "Zamknięcie (Polska)","Wejście (pkt)","Wyjście (pkt)",
                "SL (pkt)","TP (pkt)","Wynik (pkt)","ID")
        st.dataframe(pd.DataFrame(displayed,columns=fields),
                     hide_index=True,use_container_width=True)
    else:
        st.caption("Brak potwierdzonych automatycznych wejść. "
                   "Nie dodaję do archiwum samych prognoz LONG/SHORT.")
    if data["invalidated"] or data["incomplete"]:
        st.caption("Nierozliczane jako wynik: "
                   f'{data["invalidated"]} unieważnionych setupów; '
                   f'{data["incomplete"]} wierszy z brakującymi danymi.')
    st.caption(
        "Otwarcie jest modelowane na podstawie kolejnej zamkniętej świecy; "
        "bot rozpoznaje je po jej zamknięciu, nie w czasie rzeczywistym. "
        "Wyniki w punktach uwzględniają modelowane koszty i nie są "
        "wynikami zleceń brokera ani dowodem przyszłej skuteczności."
    )
