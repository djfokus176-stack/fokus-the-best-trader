"""Owner-only read-only Streamlit view of verified modeled AUTO EV.

Quant Master research cannot queue trades, promote candidates, mutate
checkpoints, or change strategy rankings used in live PAPER decisions.
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from .auto_sim_journal import SOURCE
from .quant_master_paper import quant_master_report


def _display(value, suffix=" pkt"):
    return (f"{value:+.3f}{suffix}" if isinstance(value, (float, int))
            else "BRAK DANYCH")


def _ci(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return "BRAK (za mało niezależnych sesji)"
    return f"[{value[0]:+.3f}; {value[1]:+.3f}] pkt"


def render_quant_master_research(db: sqlite3.Connection, *, epic="US500"):
    with st.expander(
        "🧪 FOKU$ QUANT MASTER — EV NETTO / LONG-SHORT / RYZYKO (PAPER)",
        expanded=False,
    ):
        st.caption(
            "NOWE BADANIA Z PDF 26.11.2026. Tylko zapisane, zamknięte "
            "transakcje AUTO v3. Brak nowych wejść, zleceń i zmian SL/TP. "
            "EV to ŚREDNIA HISTORYCZNA netto w modelowanych punktach, "
            "nie prognoza zysku ani 70% pewności.")
        cur = db.execute(
            "SELECT * FROM paper_positions_v3 WHERE source=? AND epic=?",
            (SOURCE, epic),
        )
        columns = [x[0] for x in cur.description]
        positions = [dict(zip(columns, row)) for row in cur.fetchall()]
        report = quant_master_report(positions)
        overall = report["overall"]
        st.caption(
            "Weryfikowalny rejestr: "
            f'{report["diagnostics"]["closed"]} zamkniętych AUTO; '
            f'{report["diagnostics"]["not_auto"]} wpisów innej ścieżki '
            "(nie włączono do statystyk); "
            f'{report["diagnostics"]["excluded"]} wadliwych wpisów; '
            f'{report["diagnostics"]["duplicates"]} duplikatów.')
        if not overall["n"]:
            st.info("Brak poprawnie zamkniętych pozycji AUTO. Nie liczę EV "
                    "z samych sygnałów, RAW ani historycznych backtestów.")
            return

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Zamknięte AUTO", overall["n"])
        c2.metric("Niezależne dni ET", overall["sessions"])
        c3.metric("EV zrealizowane netto / trade",
                  _display(overall["mean_net_pts"]))
        c4.metric("Max drawdown", _display(overall["max_drawdown_pts"]))
        if overall["status"] == "INSUFFICIENT_DATA":
            st.warning(
                "INSUFFICIENT_DATA: wymagane co najmniej 30 zamknięć i "
                "20 różnych dni ET w danej grupie, zanim w ogóle "
                "rozważymy test przewagi. Nawet wtedy status jest "
                "RESEARCH, nigdy automatyczne BUY/SELL.")
        st.caption(
            "95% przedział bootstrap średniego EV (próbkowanie CAŁYCH dni ET): "
            + _ci(overall["ci95_mean_net_pts"]))
        st.caption(
            "Wynik netto obejmuje już koszty modelu PAPER. "
            "Test kosztów 1,5×/2× odejmuje wyłącznie DODATKOWY "
            "koszt szacowany na podstawie zapisanego spreadu wejściowego "
            "i 2× slippage; NIE jest to prawdziwy fill brokera. "
            "Brak danych o koszcie → BRAK, nie zero.")
        a,b,c=st.columns(3)
        a.metric("EV przy 1,5× kosztach (proxy)",
                 _display(overall["stress_1_5_net_pts"]))
        b.metric("EV przy 2× kosztach (proxy)",
                 _display(overall["stress_2_net_pts"]))
        c.metric("CVaR, najgorsze 10% transakcji",
                 _display(overall["cvar10_net_pts"]))

        st.markdown("##### LONG kontra SHORT — tylko udokumentowane AUTO")
        direction=[]
        for side, row in report["per_side"].items():
            direction.append({
                "Kierunek":side,
                "Zamknięte":row["n"],
                "Sesje ET":row["sessions"],
                "Trafienia (%)":row["win_rate_pct"],
                "EV netto/trade (pkt)":row["mean_net_pts"],
                "Suma netto (pkt)":row["sum_net_pts"],
                "Próg trafień BE netto (%)":row["net_breakeven_winrate_pct"],
                "CI95 EV (pkt)":_ci(row["ci95_mean_net_pts"]),
                "Status":row["status"],
            })
        st.dataframe(pd.DataFrame(direction), hide_index=True, width="stretch")
        st.caption(
            "Próg break-even liczony z zaobserwowanych średnich "
            "dodatnich/ujemnych PnL JUŻ NETTO. Nie myl historycznej "
            "trafności z kalibrowanym prawdopodobieństwem przyszłego TP.")

        st.markdown("##### Wszystkie strategie × kierunek × polityka wyjścia")
        detail=[]
        for row in report["per_strategy"]:
            detail.append({
                "Metoda":row["strategy"],
                "Wyjście":row["policy"],
                "LONG/SHORT":row["side"],
                "N":row["n"],
                "Dni ET":row["sessions"],
                "EV netto/trade":row["mean_net_pts"],
                "EV koszt 1,5×":row["stress_1_5_net_pts"],
                "EV koszt 2×":row["stress_2_net_pts"],
                "Profit/suma netto":row["sum_net_pts"],
                "Max DD pkt":row["max_drawdown_pts"],
                "CI95":_ci(row["ci95_mean_net_pts"]),
                "Ocena":row["status"],
            })
        if detail:
            st.dataframe(pd.DataFrame(detail),
                         hide_index=True,width="stretch")
        st.markdown("##### Ostatnie 20 / 60 / 120 zaobserwowanych sesji ET")
        rolling=[]
        for days, m in report["last_sessions"].items():
            rolling.append({
                "Dni ET":days,"Transakcje":m["n"],
                "Dni obecne":m["sessions"],
                "EV netto":m["mean_net_pts"],
                "Suma netto":m["sum_net_pts"],
                "Max DD pkt":m["max_drawdown_pts"],
                "CI95":_ci(m["ci95_mean_net_pts"]),
                "Status":m["status"],
            })
        st.dataframe(pd.DataFrame(rolling),hide_index=True,width="stretch")

        st.markdown("##### CHAMPION vs CHALLENGER")
        st.info(
            "CHAMPION: obecny kod AUTO, BEZ ZMIAN. "
            "CHALLENGER: brak przetestowanej nowej strategii; "
            "NIE OGŁASZAM ZWYCIĘZCY. Do porównania potrzeba dwóch "
            "rzeczywistych strumieni forward PAPER na identycznych "
            "danych, godzinach, kosztach i limicie ryzyka.")
        st.caption(
            "MAE/MFE poszczególnych historycznych pozycji: BRAK w "
            "obecnym rejestrze v3. Nie odtwarzam ich z przyszłości "
            "ani nie oznaczam nieznanych wartości jako zero. "
            "Kalibrowane P(LONG)/P(SHORT): BRAK — wymagają osobnego "
            "prospektywnego modelu i walidacji. Dzienny risk brake "
            "oraz jakość OHLC należą do działającego workera, "
            "ten raport ich nie zmienia.")
