"""Owner UI: day/week/month PAPER archive audits from one Supabase checkpoint.

Read-only: zero broker API calls, no replay or hindsight. Explicitly shows
insufficient coverage and three independent, non-interchangeable ledgers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from .periodic_archive_audit import (
    LANES, WARSAW, period_comparison, archive_day_trades,
    _utc, _metrics, _start, _next, _at_midnight,
)
from .strategy_ranking_ui import render_strategy_ranking


POLISH={"day":"DZIEŃ","week":"TYDZIEŃ","month":"MIESIĄC"}


def _metric_display(value, decimals=2):
    if value is None:
        return "—"
    return f"{value:.{decimals}f}" if isinstance(value,float) else str(value)


def render_periodic_archive_ui(payload, *, widget_scope="terminal"):
    """Work directly with the worker's saved rows, not old data screenshots."""
    st.markdown("### 📅 AUDYT ARCHIWUM — DZIEŃ / TYDZIEŃ / MIESIĄC")
    report=payload.get("periodic_audit_report") if isinstance(payload,dict) else None
    archive=payload.get("periodic_audit_archive") if isinstance(payload,dict) else None
    if (not isinstance(report,dict) or
            report.get("status")!="ARCHIVE_AUDIT_PAPER_ONLY" or
            not isinstance(archive,dict) or archive.get("schema")!=1):
        st.warning("BRAK AUTOMATYCZNEGO AUDYTU W CHECKPOINCIE. "+
                   "Dopiero nowy skan Northflank zapisze pierwszy raport. "+
                   "Nie wyświetlam zmyślonych wyników za stare dni.")
        return
    now=datetime.now(timezone.utc)
    last=_utc(report.get("asof_utc"))
    fresh=bool(last and 0<=(now-last).total_seconds()<=600)
    st.caption(
        "Ostatni audyt UTC: "+str(report.get("asof_utc") or "BRAK")+
        " | zapisanych rozliczonych transakcji: "+
        str(report.get("stored_trades",0))+
        " | pierwszy dzień monitorowania: "+
        str(report.get("first_collected_utc") or "BRAK")+
        " | usuniętych poza limitem archiwum: "+
        str(report.get("removed_count",0))+
        ". Daty okresów: **Europe/Warsaw**. "+
        "Każdy CLOSED liczony raz według daty ZAMKNIĘCIA.")
    if not fresh:
        st.warning("Audyt nie ma świeżego potwierdzenia pracy Northflank. "+
                   "Wyniki przedstawiają wyłącznie ostatni zapis, "+
                   "a nie bieżący stan rynku.")
    today=now.astimezone(WARSAW).date()
    selected=st.date_input(
        "Wybierz dzień archiwum do porównania",
        value=today,
        min_value=today-timedelta(days=400),
        max_value=today,
        format="DD.MM.YYYY",
        key="fokus_audit_selected_day_v1_"+widget_scope)
    if isinstance(selected,tuple):
        selected=selected[0] if selected else today
    if selected is None:
        selected=today
    st.caption("Dla bieżącego dnia/tygodnia/miesiąca porównuję taki sam "+
               "UPŁYW CZASU z poprzednim okresem, a nie fragment "+
               "dzisiaj z całym wczorajszym dniem. "+
               "Wcześniejszy okres musi być objęty archiwum, "+
               "inaczej różnica jest oznaczona BRAK DANYCH.")
    # Descriptive strategy rankings from the SAME CLOSED archive, refreshed
    # on every worker audit save. Never changes AUTO selection or orders.
    render_strategy_ranking(archive,selected,
                            widget_scope=widget_scope,now=now)

    rows=[]
    for kind in ("day","week","month"):
        for lane in LANES:
            cmp=period_comparison(archive,lane,kind,reference=selected,now=now)
            current=cmp["current"]
            prev=cmp["previous_matched"]
            comparable=cmp["comparison_ready"]
            rows.append({
                "Okres":POLISH[kind],
                "Data od":cmp["period"],
                "System":lane,
                "Zamknięte":current["closed"],
                "LONG":current["long"],
                "SHORT":current["short"],
                "Trafność %":current["win_rate_pct"],
                "Netto pkt":current["net_pts"],
                "Średnio pkt":current["avg_pts"],
                "PF":current["profit_factor"],
                "Max DD pkt":current["max_drawdown_pts"],
                "Poprz. okres pkt":prev["net_pts"] if comparable else None,
                "Zmiana pkt":cmp["delta_net_pts"],
                "Ocena":("PORÓWNYWALNE" if comparable else
                         "NIEPEŁNA HISTORIA — BEZ PORÓWNANIA"),
            })
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    st.caption("PAPER v3 ≠ MOMENTUM TEST ≠ RAW M1 TEST. "+
               "Wszystkie wyniki to symulacyjne punkty netto po kosztach "+
               "modelu, nie PLN ani udowodniony zysk. "+
               "Brak danych poprzedniego okresu nie oznacza zera.")

    chosen=st.selectbox("Szczegółowa analiza metody",
                        options=list(LANES),
                        key="fokus_audit_lane_v1_"+widget_scope)
    scale=st.selectbox("Szczegółowy okres",
                       options=list(POLISH),format_func=lambda x: POLISH[x],
                       key="fokus_audit_period_v1_"+widget_scope)
    compared=period_comparison(archive,chosen,scale,reference=selected,now=now)
    d=compared["current"]
    x,y,z,w=st.columns(4)
    x.metric("Zamknięte",d["closed"])
    y.metric("Trafność",(_metric_display(d["win_rate_pct"],1)+"%")
             if d["win_rate_pct"] is not None else "BRAK")
    z.metric("Wynik netto",f'{d["net_pts"]:+.2f} pkt')
    w.metric("Max obsunięcie",f'{d["max_drawdown_pts"]:.2f} pkt')
    st.caption("TP: "+str(d["tp"])+" | SL: "+str(d["sl"])+
               " | TIMEOUT: "+str(d["timeout"])+
               " | Seria strat: "+str(d["max_losing_streak"])+
               " | PF: "+_metric_display(d["profit_factor"],2)+
               " | najlepszy: "+_metric_display(d["best_pts"],2)+
               " | najgorszy: "+_metric_display(d["worst_pts"],2))
    if not compared["comparison_ready"]:
        st.warning("Nie oceniam poprawy/pogorszenia: archiwum nie pokrywa "+
                   "całego wymaganego poprzedniego okresu. "+
                   "Pierwsza obserwacja / próg retencji UTC: "+
                   str(compared["coverage_from_utc"]))
    else:
        st.info("Poprzedni porównywalny okres: "+
                str(compared["previous_matched"]["closed"])+
                " zakończonych | "+
                f'{compared["previous_matched"]["net_pts"]:+.2f} pkt'+
                " | różnica bieżący minus poprzedni: "+
                f'{compared["delta_net_pts"]:+.2f} pkt')
    methods=d.get("methods") or {}
    if methods:
        method_data=[{"Metoda":name,"Liczba":v["count"],
                      "Trafione":v["wins"],
                      "Wynik netto pkt":v["net_pts"]}
                     for name,v in methods.items()]
        st.markdown("**Które strategie zarobiły/straciły punkty?**")
        st.dataframe(pd.DataFrame(sorted(method_data,
                 key=lambda r:r["Wynik netto pkt"],reverse=True)),
                 hide_index=True,use_container_width=True)

    with st.expander("📂 Archiwum konkretnego dnia — wszystkie rozliczone pozycje",
                     expanded=False):
        day_rows=archive_day_trades(archive,selected)
        if day_rows:
            st.caption("OPEN modelowe to start następnej świecy wg modelu, "+
                       "potwierdzenie OPEN to zamknięcie świecy, a godzina "+
                       "wykrycia przez worker pochodzi z osobnego "
                       "znacznika. Brak historycznego pola = BRAK ZAPISU.")
            table=pd.DataFrame(day_rows)
            st.dataframe(table,hide_index=True,use_container_width=True)
            st.download_button(
                "Pobierz CSV rozliczeń tego dnia",
                data=table.to_csv(index=False).encode("utf-8-sig"),
                file_name="FOKUS_AUDYT_"+selected.isoformat()+".csv",
                mime="text/csv",
                key="fokus_audit_download_v1_"+widget_scope)
        else:
            st.caption("W archiwum audytu nie ma rozliczonych pozycji z "+
                       str(selected)+". To może oznaczać brak transakcji "+
                       "albo niepełne archiwum — sprawdź datę startu.")

    with st.expander("📊 Historia porównawcza — ostatnie dni, tygodnie i miesiące",
                     expanded=False):
        summary=[]
        for kind,count in (("day",14),("week",8),("month",6)):
            cursor=_start(kind,selected)
            for _ in range(count):
                start,end=_at_midnight(cursor),_at_midnight(_next(kind,cursor))
                stats=_metrics(archive,chosen,start,min(end,now))
                summary.append({
                    "Okres":POLISH[kind],
                    "Od":cursor.isoformat(),
                    "Zamknięte":stats["closed"],
                    "Trafność %":stats["win_rate_pct"],
                    "Netto pkt":stats["net_pts"],
                    "PF":stats["profit_factor"],
                })
                if kind=="day":
                    cursor=cursor-timedelta(days=1)
                elif kind=="week":
                    cursor=cursor-timedelta(days=7)
                else:
                    cursor=cursor.replace(month=cursor.month-1) if cursor.month>1 else cursor.replace(year=cursor.year-1,month=12)
        st.dataframe(pd.DataFrame(summary),hide_index=True,use_container_width=True)
        st.caption("Lista pokazuje wyłącznie zachowane rozliczenia "+
                   "i może obejmować okresy przed początkiem pełnego audytu.")
