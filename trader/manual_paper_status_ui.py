"""Live OWNER-ONLY manual PAPER status (read-only Supabase polling).

This fragment displays a precise QUEUED -> PENDING -> OPEN -> CLOSED
heartbeat; it cannot place a second request or call a broker. Full chart
rerender is triggered ONLY when the trade state changes, not on every
checkpoint heartbeat.
"""
from __future__ import annotations

from datetime import datetime,timezone

import pandas as pd
import streamlit as st

from .remote_checkpoint import RemoteError


def _time(value):
    if value is None:
        return None
    try:
        t=pd.Timestamp(value)
    except (TypeError,ValueError,OverflowError):
        return None
    if pd.isna(t) or t.tzinfo is None:
        return None
    return t.tz_convert("UTC")


def _local(t):
    return t.tz_convert("Europe/Warsaw").strftime("%d.%m.%Y %H:%M:%S") if t is not None else "BRAK"


def _status(report):
    req=report.get("request") if isinstance(report.get("request"),dict) else {}
    active=report.get("active") if isinstance(report.get("active"),dict) else {}
    return (str(active.get("status") or req.get("status") or "BRAK"),
            str(active.get("side") or req.get("side") or "BRAK"))


def _explain(reason):
    reason=str(reason or "")
    messages={
        "WORKER_DATA_STALE":"Worker skanował, ale dane M1 były STARE. Nie wolno potwierdzić wejścia.",
        "WORKER_NO_M1_FEED":"Worker skanował, ale broker nie dostarczył M1.",
        "WORKER_MARKET_CLOSED":"Rynek oznaczony przez brokera jako zamknięty.",
        "WORKER_NOT_DEMO":"Skan nie był prowadzony w DEMO.",
        "WAIT_WORKER_NO_NEW_M1":"Worker pracuje, ale nie uzyskał nowej poprawnej zamkniętej M1.",
        "WAIT_FRESH_M1_CLOSE":"Świeca M1 była za stara lub miała nieprawidłowy czas.",
        "WAIT_VERIFIED_M1":"Brak wystarczającej liczby kolejnych, zweryfikowanych świec M1.",
        "WAIT_SPREAD_TOO_HIGH":"Zbyt szeroki spread — bez wymuszonego wejścia po złej cenie.",
        "WAIT_WORKER_GLOBAL_GATES":"Blokada techniczna silnika PAPER lub brak zgody na nowe setupy.",
        "WAIT_NEXT_M1_AFTER_CLICK":"Najnowsza M1 pochodzi sprzed kliknięcia. Potrzebna kolejna.",
        "PENDING_NEXT_VERIFIED_M1":"PENDING: sygnał zapisany. OPEN dopiero na następnej poprawnej M1.",
        "EXPIRED_NO_VALID_M1":"Żądanie wygasło po 15 minutach bez poprawnego wejścia.",
        "WAIT_MARKET_NOT_TRADEABLE":"Rynek nie ma statusu TRADEABLE.",
        "WAIT_DEMO_SOURCE":"Niezgodne źródło danych — nie otwieram testu.",
    }
    return messages.get(reason,reason or "Brak potwierdzonej decyzji workera")


def manual_status_panel(remote):
    """Use within owner-authenticated terminal. No write actions at all."""
    @st.fragment(run_every="12s")
    def show():
        try:
            _,payload=remote.fetch()
            report=payload.get("manual_paper_test_report") or {}
            meta=payload.get("meta") or {}
        except (RemoteError,ValueError,TypeError,KeyError,OverflowError,OSError):
            st.warning("Nie udało się odczytać NAJNOWSZEGO statusu z Supabase. "
                       "Nie zakładam, że pozycja została otwarta.")
            return
        if report.get("status")!="OWNER_MANUAL_PAPER_ONLY":
            st.warning("Brak raportu ręcznego testu w aktualnym checkpoint. "
                       "Sprawdź wdrożoną wersję workera Northflank.")
            return

        req=report.get("request") if isinstance(report.get("request"),dict) else {}
        active=report.get("active") if isinstance(report.get("active"),dict) else {}
        current,side=_status(report)
        # Change of actual OPEN/CLOSED state should also update the main
        # candlestick figure; don't rerender entire app for idle heartbeats.
        sig=(current,side,str(report.get("opened",0)),
             str(report.get("closed",0)),str(report.get("last_candle_utc") or ""))
        previous=st.session_state.get("_manual_paper_chart_status_signature")
        st.session_state["_manual_paper_chart_status_signature"]=sig
        if previous is not None and previous[:4]!=sig[:4]:
            st.session_state.pop("_fokus_cloud_chart_cache_v3",None)
            st.rerun(scope="app")

        a,b,c,d=st.columns(4)
        a.metric("TEST: żądania",report.get("requested",0))
        b.metric("TEST: OPEN łącznie",report.get("opened",0))
        c.metric("TEST: CLOSED",report.get("closed",0))
        d.metric("TEST: netto",str(report.get("pnl_pts",0))+" pkt")

        now=pd.Timestamp.now(tz="UTC")
        requested=_time(req.get("requested_utc"))
        worker_attempt=_time(report.get("last_worker_attempt_utc"))
        last_scan=_time(meta.get("last_scan_utc"))
        last_m1=_time(report.get("last_candle_utc"))
        st.caption("Żądanie: "+_local(requested)+
                   " (PL) | Ostatnia próba skanu workera: "+
                   _local(worker_attempt)+
                   " (PL) | Ostatnia zweryfikowana M1 testu: "+
                   _local(last_m1)+" (PL).")

        if requested is not None and current in ("QUEUED","WAIT_DATA"):
            if worker_attempt is None or worker_attempt<requested:
                st.warning("⏳ "+side+" ma status "+current+
                           ". ŻĄDANIE ZAPISANE, lecz BRAK POTWIERDZENIA "
                           "nowego skanu Northflank po kliknięciu. "
                           "Nie jest to otwarta pozycja.")
            else:
                st.warning("⏳ Worker wykonał skan po Twoim kliknięciu, "
                           "ale NIE otworzył jeszcze pozycji. "+
                           _explain(report.get("last_reason")))
            waited=(now-requested).total_seconds()/60
            if waited>15:
                st.error("Minęło ponad 15 minut od kliknięcia. Jeśli "
                         "Northflank nie skanuje, żądanie może nadal "
                         "figurować jako QUEUED; wygaśnięcie zapisze "
                         "dopiero kolejny skan workera. Nie klikaj drugi raz.")
        elif current=="PENDING":
            st.info("⏳ RĘCZNY "+side+" PENDING — czekam na następną "
                    "zweryfikowaną świecę M1. To NIE jest OPEN. "
                    "SL "+str(active.get("stop"))+
                    " | TP "+str(active.get("target")))
        elif current=="OPEN":
            st.success("🟢 RĘCZNY "+side+" OPEN — symulowana pozycja "
                       "jest aktywna. Wejście MID: "+
                       str(active.get("entry_mid"))+
                       " | SL: "+str(active.get("stop"))+
                       " | TP: "+str(active.get("target"))+
                       " | zamknięte M1 w pozycji: "+
                       str(active.get("bars_held",0))+"/5.")
        elif current=="ACCEPTED":
            st.info("Test zaakceptowany przez workera. "
                    "Ostatni status: "+_explain(report.get("last_reason")))
        else:
            st.info("Status ręcznego testu: "+current+
                    " | "+_explain(report.get("last_reason")))

        if last_scan is None or (now-last_scan).total_seconds()>180:
            st.error("⚠️ GŁÓWNY CHECKPOINT STARY: Northflank nie zapisał "
                     "świeżego skanu w ciągu ostatnich 3 minut. "
                     "To może tłumaczyć brak OPEN.")
        if report.get("last_worker_diagnosis") in (
                "WORKER_DATA_STALE","WORKER_NO_M1_FEED",
                "WORKER_MARKET_CLOSED","WORKER_NOT_DEMO"):
            st.caption("Diagnoza ostatniego skanu: "+
                       _explain(report.get("last_worker_diagnosis")))

        recent=report.get("recent") or []
        if isinstance(recent,list) and recent:
            with st.expander("📓 Ostatnie zamknięcia ręcznych LONG/SHORT",
                             expanded=False):
                rows=[]
                for p in recent[:12]:
                    opened=_time(p.get("opened_utc"))
                    closed=_time(p.get("closed_utc"))
                    rows.append({
                        "Kierunek":p.get("side"),
                        "OPEN (Polska)":_local(opened),
                        "CLOSE (Polska)":_local(closed),
                        "Powód":p.get("status"),
                        "Wejście pkt":p.get("entry_mid"),
                        "Wyjście pkt":p.get("exit_mid"),
                        "Netto pkt":p.get("pnl_pts"),
                    })
                st.dataframe(pd.DataFrame(rows),hide_index=True,
                             width="stretch")
        invalid=report.get("invalidated_recent") or []
        if invalid:
            st.warning(str(len(invalid))+
                       " testów bez rozliczenia przez brak pewnych danych. "
                       "P&L pozostaje NIEZNANE, nie 0 pkt.")

    show()
